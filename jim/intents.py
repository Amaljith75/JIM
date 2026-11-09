"""Instant voice commands - no LLM round-trip needed.

"open spotify", "next tab", "volume up", "search for esp32 pinout",
"open chrome and then go to tab 3" ... are matched here and executed in
milliseconds. Anything that doesn't match goes to the LLMs, which can still
call the same tools.
"""
from __future__ import annotations

import re

ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
            "eighth": 8, "last": 9, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8}
NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty five": 45,
                "half an": 0.5, "half a": 0.5}

_FILLER = r"(?:the |a |my |this |current |that )?"


def _num(s: str) -> float | None:
    s = s.strip().lower()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    return NUMBER_WORDS.get(s)


def _tab_n(s: str) -> int | None:
    s = s.strip().lower()
    if s.isdigit():
        return int(s)
    return ORDINALS.get(s)


def clean(text: str, wake_word: str = "jim") -> str:
    t = text.strip()
    t = re.sub(rf"^(?:hey|hi|ok|okay|yo)?\s*,?\s*{re.escape(wake_word)}\b[\s,.!:]*", "", t, flags=re.I)
    t = re.sub(r"^(?:can you|could you|would you|will you|please|kindly|i want you to|i need you to)\s+", "", t, flags=re.I)
    t = re.sub(r"\s*(?:please|for me|now|right now|thanks|thank you)[\s.!?]*$", "", t, flags=re.I)
    return t.strip(" .!?,")


# (regex, handler) ; handler returns (tool, args) or None
RULES: list[tuple[re.Pattern, callable]] = []


def rule(pattern: str):
    def deco(fn):
        RULES.append((re.compile(rf"^(?:{pattern})$", re.I), fn))
        return fn
    return deco


# ---- browser tabs (before generic open/close so "close tab" isn't an app)
@rule(rf"(?:go to |switch to |move to )?(?:the )?next tab|tab right|switch tabs?|change tab")
def _(m): return "next_tab", {}

@rule(rf"(?:go to |switch to |move to )?(?:the )?(?:previous|prev|last|left) tab|tab left|go back a tab")
def _(m): return ("go_to_tab", {"number": 9}) if "last" in m.group(0).lower() and "go to" in m.group(0).lower() else ("previous_tab", {})

@rule(r"(?:go to |switch to |open |show )?(?:the )?tab (?:number )?(\w+)|(?:go to |switch to )?(?:the )?(\w+) tab")
def _(m):
    n = _tab_n(m.group(1) or m.group(2) or "")
    return ("go_to_tab", {"number": n}) if n else None

@rule(rf"(?:open |create |make )?(?:a )?new tab")
def _(m): return "new_tab", {}

@rule(rf"close {_FILLER}tab")
def _(m): return "close_tab", {}

@rule(r"(?:reopen|restore|undo close|bring back)(?: the)?(?: last| closed)*(?: closed)? tab")
def _(m): return "reopen_tab", {}

@rule(r"refresh|reload|refresh (?:the )?page|reload (?:the )?page")
def _(m): return "refresh", {}

@rule(r"go back|back|previous page")
def _(m): return "go_back", {}

@rule(r"go forward|forward|next page")
def _(m): return "go_forward", {}

@rule(r"zoom (in|out)|reset zoom")
def _(m): return "zoom", {"direction": (m.group(1) or "reset").lower()}

# ---- windows
@rule(r"switch (?:to (?:the )?next )?(?:window|app|application)s?|next window|alt tab|change window")
def _(m): return "switch_window", {}

@rule(rf"minimi[sz]e{'(?: ' + _FILLER + 'window)?'}|hide {_FILLER}window")
def _(m): return "minimize_window", {}

@rule(rf"maximi[sz]e{'(?: ' + _FILLER + 'window)?'}|full ?screen{'(?: ' + _FILLER + 'window)?'}")
def _(m): return "maximize_window", {}

@rule(rf"close {_FILLER}window")
def _(m): return "close_window", {}

@rule(r"show (?:me )?(?:the )?desktop|minimi[sz]e (?:all|everything)|go to (?:the )?desktop")
def _(m): return "show_desktop", {}

# ---- media / volume
@rule(r"(?:turn (?:the )?)?volume up|turn it up|louder|increase (?:the )?volume|raise (?:the )?volume")
def _(m): return "volume_up", {}

@rule(r"(?:turn (?:the )?)?volume down|turn it down|quieter|softer|decrease (?:the )?volume|lower (?:the )?volume")
def _(m): return "volume_down", {}

@rule(r"mute|unmute|mute (?:the )?(?:sound|audio|volume)|silence")
def _(m): return "mute", {}

@rule(r"pause|play|resume|pause (?:the )?(?:music|song|video|media)|play (?:the )?(?:music|song|video|media)|resume (?:the )?(?:music|song|video)|stop (?:the )?(?:music|song)")
def _(m): return "play_pause", {}

@rule(r"next (?:song|track|video)|skip(?: (?:this|the))?(?: song| track)?")
def _(m): return "next_track", {}

@rule(r"previous (?:song|track|video)|last (?:song|track)|go back a (?:song|track)")
def _(m): return "previous_track", {}

# ---- scrolling / typing
@rule(r"scroll (up|down)(?: (?:a lot|more))?")
def _(m): return "scroll", {"direction": m.group(1).lower(), "amount": 10 if re.search(r"lot|more", m.group(0), re.I) else 5}

@rule(r"(?:type|dictate) (.+)")
def _(m): return "type_text", {"text": m.group(1)}

@rule(r"press (?:the )?(.+?)(?: key| keys)?")
def _(m): return "press_keys", {"keys": m.group(1).replace(" plus ", "+").replace(" and ", "+")}

# ---- search
@rule(r"(?:search|look up|find|play) (.+?) on youtube|youtube (.+)|(?:search )?youtube for (.+)")
def _(m): return "youtube", {"query": re.sub(r"^for ", "", next(g for g in m.groups() if g))}

@rule(r"(?:search(?: the web| google)?(?: for)?|google|look up) (.+)")
def _(m): return "web_search", {"query": m.group(1)}

# ---- system
@rule(r"(?:take (?:a )?)?screen ?shot|capture (?:the )?screen")
def _(m): return "screenshot", {}

@rule(r"lock(?: the| my)? (?:screen|computer|pc|laptop|system)|lock it")
def _(m): return "lock_screen", {}

@rule(r"(?:system|computer|pc) (?:status|info|stats|health)|(?:how(?:'s| is) )?(?:my |the )?(?:battery|cpu|ram|memory)(?: usage| level| status)?")
def _(m): return "system_info", {}

@rule(r"(?:what(?:'s| is) the )?time(?: is it)?|what time is it|(?:what(?:'s| is) )?(?:the |today's )?date(?: today)?|what day is (?:it|today)")
def _(m): return "current_time", {}

@rule(r"shut ?down(?: the| my)?(?: computer| pc| laptop| system)?|power off")
def _(m): return "shutdown", {}

@rule(r"restart(?: the| my)?(?: computer| pc| laptop| system)?|reboot")
def _(m): return "restart", {}

@rule(r"(?:go to )?sleep(?: mode)?|put (?:the |my )?(?:computer|pc|laptop) to sleep")
def _(m): return "sleep_computer", {}

@rule(r"(?:set (?:a )?)?timer (?:for )?(.+?) (seconds?|secs?|minutes?|mins?|hours?)|(?:set )?(?:a )?(.+?) (seconds?|secs?|minutes?|mins?|hours?) timer")
def _(m):
    amount = _num(m.group(1) or m.group(3) or "")
    unit = (m.group(2) or m.group(4) or "").lower()
    if amount is None:
        return None
    mult = 3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1
    return "set_timer", {"seconds": int(amount * mult), "label": "Timer"}

@rule(r"remember (?:that )?(.+)")
def _(m): return "remember", {"fact": m.group(1)}

@rule(r"forget (?:about |that )?(.+)")
def _(m): return None if m.group(1).lower() in {"it", "that", "this"} else ("forget", {"text": m.group(1)})

# ---- folders, sites, apps (generic - keep last)
@rule(r"(?:open|show)(?: my| the)? (downloads|documents|desktop|pictures|photos|music|videos|home)(?: folder)?")
def _(m): return "open_folder", {"path": m.group(1).lower()}

@rule(r"(?:open|go to|visit|navigate to) ((?:https?://)?[\w-]+(?:\.[\w-]+)+(?:/\S*)?)")
def _(m): return "open_url", {"url": m.group(1)}

@rule(r"(?:open|launch|start|run|fire up|bring up) (?:the |my |up )?([\w .+'-]{1,40}?)(?: app| application| program)?")
def _(m):
    name = m.group(1).strip()
    if len(name.split()) > 4 or " and " in f" {name.lower()} " or name.lower() in {"over", "again", "it", "up"}:
        return None
    return "open_app", {"name": name}

@rule(r"go to ([\w .-]{1,30})")
def _(m):
    from .actions import WEBSITES
    name = m.group(1).strip().lower()
    return ("open_url", {"url": name}) if name in WEBSITES else None

@rule(r"(?:close|quit|exit|kill|terminate) (?:the |my )?([\w .+'-]{1,40}?)(?: app| application| program)?")
def _(m):
    name = m.group(1).strip()
    if len(name.split()) > 4 or " and " in f" {name} " or name in {"it", "this", "that"}:
        return None
    return "close_app", {"name": name}


SPLIT = re.compile(r"\s*(?:,\s*)?\b(?:and then|then|and also|and|after that)\b\s*|\s*[;,]\s*")


def _known(name: str) -> bool:
    from .actions import APPS, ALIASES, WEBSITES, canonical_app
    key = canonical_app(name)
    return key in APPS or key in WEBSITES or name.lower() in ALIASES


def match_one(text: str) -> tuple[str, dict] | None:
    for rx, fn in RULES:
        m = rx.match(text)
        if m:
            res = fn(m)
            if res:
                return res
    return None


def match(text: str, wake_word: str = "jim") -> list[tuple[str, dict]] | None:
    """Return a list of (tool, args) if the WHOLE utterance is commands, else None."""
    t = clean(text, wake_word)
    if not t or len(t) > 200:
        return None
    single = match_one(t)
    # "type"/"search" commands swallow the rest of the sentence on purpose
    if single and single[0] in {"type_text", "web_search", "youtube", "remember"}:
        return [single]
    parts = [p.strip() for p in SPLIT.split(t) if p and p.strip()]
    if len(parts) > 1:
        cmds, verb = [], ""
        for p in parts:
            c = match_one(clean(p, wake_word))
            if not c and verb:                      # "open chrome and spotify" -> "open spotify"
                c = match_one(f"{verb} {p}")
                if c and c[0] in ("open_app", "close_app") and not _known(c[1]["name"]):
                    c = None                        # "open notepad and tell me a joke" -> LLM
            cmds.append(c)
            verb = p.split()[0] if c else verb
        if all(cmds):
            return cmds  # type: ignore[return-value]
    return [single] if single else None


ACKS = {
    "jim": ["Right away.", "Done, sir.", "Consider it done.", "On it."],
    "pro": ["Done.", "Completed."],
    "buddy": ["Gotcha!", "On it!", "Done and done 😎"],
    "sarcastic": ["Fine.", "As you wish, your majesty.", "Wow, so hard. Done."],
    "teacher": ["Done!", "All set."],
    "hype": ["Let's GO!", "Boom, done!", "Crushed it!"],
    "zen": ["It is done.", "Gently done."],
    "engineer": ["Executed.", "Done."],
}
