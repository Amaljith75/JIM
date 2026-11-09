"""JIM HTTP server (FastAPI). Serves the web UI and the JSON/streaming API."""
from __future__ import annotations

import json
import os
import secrets
import tempfile

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import actions, config, llm, memory, orchestrator
from .config import ROOT

app = FastAPI(title="JIM", docs_url="/api/docs")
TOKEN = os.environ.get("JIM_TOKEN", "")


@app.middleware("http")
async def auth(request: Request, call_next):
    """When JIM is exposed on the network, every API call needs the access token."""
    if TOKEN and request.url.path.startswith("/api"):
        given = request.headers.get("x-jim-token") or request.query_params.get("token", "")
        if not secrets.compare_digest(given, TOKEN):
            return JSONResponse({"detail": "Invalid or missing access token"}, status_code=401)
    return await call_next(request)


# ------------------------------------------------------------------ state
@app.get("/api/state")
def state():
    return {
        "settings": config.settings(),
        "personalities": config.personalities(),
        "providers": [config.public_provider(p) for p in config.providers()],
        "tools": actions.tools_public(),
        "platform": actions.platform_name(),
        "dry_run": actions.DRY_RUN,
    }


@app.post("/api/settings")
async def save_settings(req: Request):
    return config.update_settings(await req.json())


# ------------------------------------------------------------------- chat
@app.post("/api/chat")
async def chat(req: Request):
    body = await req.json()
    text = (body.get("message") or "").strip()
    if not text:
        raise HTTPException(400, "Empty message")

    async def gen():
        try:
            async for e in orchestrator.handle(text, body.get("conversation_id"), body.get("mode"), body.get("provider_id")):
                yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
        except Exception as e:  # surface unexpected errors to the UI instead of a silent hang
            yield f"data: {json.dumps({'type': 'error', 'text': f'{type(e).__name__}: {e}'})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'text': ''})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/chat/sync")
async def chat_sync(req: Request):
    """Non-streaming chat for the voice daemon, scripts, phone shortcuts etc."""
    body = await req.json()
    text, acts, cid, errors, provider = "", [], None, [], ""
    async for e in orchestrator.handle(body.get("message", ""), body.get("conversation_id"), body.get("mode")):
        t = e["type"]
        if t == "done":
            text = e["text"]
        elif t == "action":
            acts.append(e["result"])
        elif t == "conversation":
            cid = e["id"]
        elif t == "error":
            errors.append(e["text"])
        elif t == "meta":
            provider = e["provider"]
    return {"text": text or "\n".join(errors), "actions": acts, "conversation_id": cid, "provider": provider}


@app.post("/api/action")
async def run_action(req: Request):
    body = await req.json()
    return actions.run(body["tool"], body.get("args") or {}, confirmed=bool(body.get("confirmed")))


# -------------------------------------------------------------- providers
@app.get("/api/providers")
def list_providers():
    return [config.public_provider(p) for p in config.providers()]


@app.post("/api/providers")
async def save_provider(req: Request):
    data = await req.json()
    if not data.get("name") or not data.get("base_url"):
        raise HTTPException(400, "Name and base URL are required")
    return config.public_provider(config.upsert_provider(data))


@app.delete("/api/providers/{pid}")
def remove_provider(pid: str):
    config.delete_provider(pid)
    return {"ok": True}


@app.post("/api/providers/{pid}/test")
async def test_provider(pid: str):
    p = config.get_provider(pid)
    if not p:
        raise HTTPException(404, "Unknown provider")
    try:
        reply = await llm.test(p)
        return {"ok": True, "reply": reply[:80]}
    except llm.LLMError as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/providers/{pid}/models")
async def provider_models(pid: str):
    p = config.get_provider(pid)
    if not p:
        raise HTTPException(404, "Unknown provider")
    try:
        return {"ok": True, "models": await llm.list_models(p)}
    except Exception as e:
        return {"ok": False, "error": str(e), "models": []}


# ---------------------------------------------------------- personalities
@app.post("/api/personalities")
async def save_personality(req: Request):
    return config.upsert_personality(await req.json())


@app.delete("/api/personalities/{pid}")
def remove_personality(pid: str):
    if len(config.personalities()) <= 1:
        raise HTTPException(400, "Keep at least one personality")
    config.delete_personality(pid)
    return {"ok": True}


# ---------------------------------------------------------- conversations
@app.get("/api/conversations")
def list_conversations():
    return memory.conversations()


@app.get("/api/conversations/{cid}")
def get_conversation(cid: str):
    return memory.messages(cid)


@app.delete("/api/conversations/{cid}")
def remove_conversation(cid: str):
    memory.delete_conversation(cid)
    return {"ok": True}


@app.get("/api/facts")
def list_facts():
    return memory.facts()


@app.post("/api/facts")
async def add_fact(req: Request):
    memory.add_fact((await req.json())["fact"])
    return {"ok": True}


@app.delete("/api/facts/{fid}")
def remove_fact(fid: int):
    memory.delete_fact(fid)
    return {"ok": True}


# ------------------------------------------------------- offline speech
_whisper = {"name": None, "model": None}


@app.post("/api/transcribe")
async def transcribe(req: Request):
    """Offline speech-to-text with faster-whisper. Body = raw audio (webm/ogg/wav)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise HTTPException(501, "Offline speech needs faster-whisper: pip install -r requirements-voice.txt")
    name = config.settings().get("whisper_model", "base")
    if _whisper["name"] != name:
        _whisper["model"] = WhisperModel(name, device="auto", compute_type="int8")
        _whisper["name"] = name
    audio = await req.body()
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(audio)
        path = f.name
    try:
        segments, info = _whisper["model"].transcribe(path, vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
    finally:
        os.unlink(path)
    return {"text": text, "language": info.language}


# ------------------------------------------------------------------- web
WEB = ROOT / "web"
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(WEB / "manifest.webmanifest", media_type="application/manifest+json")
