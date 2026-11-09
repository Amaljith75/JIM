"""JIM's brain: combines several LLMs and turns their replies into actions.

Modes
-----
auto     Try providers in priority order; if one fails or is rate-limited, fall
         through to the next. Fast and robust - the default.
single   Always use one chosen provider.
race     Ask every enabled provider at once and take the first good answer.
council  Ask several providers in parallel, then a "synthesizer" model merges
         their answers into one better answer (slowest, highest quality).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import random
import re
from typing import AsyncIterator

from . import actions, config, intents, llm, memory

ACTION_TAG = "[[ACTION:"


# ---------------------------------------------------------------- prompts
def system_prompt(with_tools: bool = True) -> str:
    s = config.settings()
    per = config.get_personality(s["personality"])
    name = s.get("assistant_name") or "JIM"
    lines = [
        f"You are {name}, a personal AI assistant running on the user's own computer ({actions.platform_name()}).",
        f"Personality: {per['prompt']}",
        f"Current local time: {dt.datetime.now():%A %d %B %Y, %I:%M %p}.",
        "Replies may be read aloud, so keep them conversational and concise unless the user asks for detail. "
        "Use markdown only when it really helps (code, lists).",
    ]
    if s.get("user_name"):
        lines.append(f"The user's name is {s['user_name']}.")
    facts = memory.facts()
    if facts:
        lines.append("Things you know about the user:\n" + "\n".join(f"- {f['fact']}" for f in facts[-40:]))
    if with_tools and s.get("allow_system_control"):
        lines.append(
            "\nYou can control the user's computer. To perform an action, write an action tag on its own line, "
            'exactly like: [[ACTION:{"tool": "open_app", "args": {"name": "spotify"}}]]\n'
            "You may use several tags in one reply. Only use a tool when the user asks for something to be done on "
            "their computer; briefly say what you're doing in words too. Never invent tools. Available tools:\n"
            + actions.tools_for_prompt()
        )
    return "\n".join(lines)


def build_messages(cid: str, user_text: str, with_tools: bool = True) -> list[dict]:
    s = config.settings()
    msgs = [{"role": "system", "content": system_prompt(with_tools)}]
    msgs += memory.history(cid, int(s.get("history_turns", 12)))
    msgs.append({"role": "user", "content": user_text})
    return msgs


# ---------------------------------------------------------- action parsing
def extract_actions(text: str) -> tuple[str, list[dict]]:
    """Pull [[ACTION:{...}]] tags out of a reply. Returns (clean_text, actions)."""
    found, out, i = [], [], 0
    dec = json.JSONDecoder()
    while True:
        j = text.find(ACTION_TAG, i)
        if j < 0:
            out.append(text[i:])
            break
        out.append(text[i:j])
        k = j + len(ACTION_TAG)
        try:
            obj, end = dec.raw_decode(text, k)
            end_tag = text.find("]]", end)
            i = end_tag + 2 if end_tag >= 0 else end
            if isinstance(obj, dict) and obj.get("tool"):
                found.append({"tool": obj["tool"], "args": obj.get("args") or {}})
        except json.JSONDecodeError:
            end_tag = text.find("]]", k)
            i = end_tag + 2 if end_tag >= 0 else len(text)
    clean = re.sub(r"\n{3,}", "\n\n", "".join(out)).strip()
    return clean, found


def ev(kind: str, **data) -> dict:
    return {"type": kind, **data}


# ------------------------------------------------------------------ modes
async def _auto(providers: list[dict], msgs: list[dict], s: dict) -> AsyncIterator[dict]:
    errors = []
    for p in providers:
        started = False
        try:
            async for tok in llm.stream(p, msgs, s["temperature"], s["max_tokens"]):
                if not started:
                    started = True
                    yield ev("meta", provider=p["name"], model=p["model"], mode="auto")
                yield ev("token", text=tok)
            if started:
                return
            errors.append(f"{p['name']}: empty reply")
        except llm.LLMError as e:
            errors.append(str(e))
            if started:
                yield ev("token", text=f"\n\n_(connection to {p['name']} dropped)_")
                return
            yield ev("notice", text=f"{p['name']} unavailable, trying next model…")
    yield ev("error", text="All models failed:\n" + "\n".join(errors))


async def _race(providers: list[dict], msgs: list[dict], s: dict) -> AsyncIterator[dict]:
    async def one(p):
        return p, await llm.complete(p, msgs, s["temperature"], s["max_tokens"])

    tasks = [asyncio.create_task(one(p)) for p in providers]
    errors = []
    try:
        for fut in asyncio.as_completed(tasks):
            try:
                p, text = await fut
                if not text:
                    continue
                yield ev("meta", provider=p["name"], model=p["model"], mode="race")
                for chunk in _chunks(text):
                    yield ev("token", text=chunk)
                return
            except llm.LLMError as e:
                errors.append(str(e))
        yield ev("error", text="All models failed:\n" + "\n".join(errors))
    finally:
        for t in tasks:
            t.cancel()


async def _council(providers: list[dict], cid: str, user_text: str, s: dict) -> AsyncIterator[dict]:
    members = providers[: max(2, int(s.get("council_size", 3)))]
    member_msgs = build_messages(cid, user_text, with_tools=False)
    member_msgs[0]["content"] += "\nAnswer the user's message directly and accurately."
    yield ev("notice", text=f"Council of {len(members)} models thinking: " + ", ".join(p["name"] for p in members))

    async def one(p):
        try:
            return p, await asyncio.wait_for(llm.complete(p, member_msgs, s["temperature"], s["max_tokens"]), 90)
        except (llm.LLMError, asyncio.TimeoutError) as e:
            return p, e

    results = await asyncio.gather(*(one(p) for p in members))
    good = [(p, r) for p, r in results if isinstance(r, str) and r.strip()]
    for p, r in results:
        if not isinstance(r, str):
            yield ev("notice", text=f"{p['name']} failed: {str(r)[:160] or type(r).__name__}")
    yield ev("council", answers=[{"provider": p["name"], "model": p["model"], "text": r} for p, r in good])

    if not good:
        yield ev("error", text="No council member answered.")
        return

    synth_id = s.get("synthesizer")
    synth_order = sorted(providers, key=lambda p: p["id"] != synth_id)  # chosen synthesizer first
    joined = "\n\n".join(f"### Answer {i + 1} ({p['name']})\n{r}" for i, (p, r) in enumerate(good))
    synth_msgs = build_messages(cid, user_text, with_tools=True)
    synth_msgs[-1]["content"] = (
        f"{user_text}\n\n---\nSeveral AI models drafted answers to the message above:\n\n{joined}\n\n---\n"
        "Write the single best final reply to the user in your own voice and personality. Combine the strongest "
        "points, correct any mistakes, resolve disagreements, and drop anything wrong or redundant. Do not mention "
        "the drafts or other models unless the user asks. If the user asked for a computer action, include the action tag."
    )
    async for e in _auto(synth_order, synth_msgs, s):
        if e["type"] == "meta":
            e = ev("meta", provider=f"Council → {e['provider']}", model=e["model"], mode="council")
        yield e


def _chunks(text: str, size: int = 24):
    for i in range(0, len(text), size):
        yield text[i:i + size]


# --------------------------------------------------------------- main entry
async def handle(user_text: str, cid: str | None = None, mode: str | None = None,
                 provider_id: str | None = None) -> AsyncIterator[dict]:
    s = config.settings()
    cid = memory.ensure_conversation(cid, user_text)
    yield ev("conversation", id=cid)
    memory.add_message(cid, "user", user_text)

    # 1) instant commands
    cmds = intents.match(user_text, s.get("wake_word", "jim")) if s.get("allow_system_control") else None
    if cmds:
        results = [actions.run(t, a) for t, a in cmds]
        lone_app_miss = len(results) == 1 and not results[0]["ok"] and results[0]["tool"] == "open_app"
        if not lone_app_miss:
            for r in results:
                yield ev("action", result=r)
            ok_msgs = [r["message"] for r in results if r["ok"]]
            bad_msgs = [r["message"] for r in results if not r["ok"] and not r.get("needs_confirm")]
            ack = random.choice(intents.ACKS.get(s["personality"], ["Done."])) if len(ok_msgs) > 1 else ""
            reply = " ".join(filter(None, [ack, *ok_msgs, *bad_msgs])) or "Waiting for your confirmation."
            yield ev("meta", provider="Instant command", model="local", mode="command")
            yield ev("token", text=reply)
            memory.add_message(cid, "assistant", reply, json.dumps({"provider": "command"}))
            yield ev("done", text=reply)
            return

    # 2) LLMs
    providers = config.enabled_providers()
    if not providers:
        msg = ("No AI models are set up yet. Open ⚙ Settings → Models and add an API key (Groq and Gemini are free), "
               "or install Ollama to run a model offline.")
        yield ev("error", text=msg)
        yield ev("done", text=msg)
        return

    mode = mode or s.get("mode", "auto")
    pid = provider_id or s.get("single_provider")
    full = ""
    meta = {}
    if mode == "single" and pid:
        chosen = [p for p in providers if p["id"] == pid]
        gen = _auto(chosen or providers, build_messages(cid, user_text), s)
    elif mode == "race" and len(providers) > 1:
        gen = _race(providers, build_messages(cid, user_text), s)
    elif mode == "council" and len(providers) > 1:
        gen = _council(providers, cid, user_text, s)
    else:
        gen = _auto(providers, build_messages(cid, user_text), s)

    async for e in gen:
        if e["type"] == "token":
            full += e["text"]
        elif e["type"] == "meta":
            meta = e
        yield e

    clean, acts = extract_actions(full)
    for a in acts:
        yield ev("action", result=actions.run(a["tool"], a["args"]))
    if clean or acts:
        memory.add_message(cid, "assistant", clean or "(done)", json.dumps({"provider": meta.get("provider", "")}))
    yield ev("done", text=clean)
