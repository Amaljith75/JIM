"""Configuration storage for JIM: providers, personalities, settings.

Everything lives in plain JSON under ./data so you can back it up or edit by hand.
Defaults ship in ./config and are copied into ./data on first run.
"""
from __future__ import annotations

import json
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULTS_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

_lock = threading.RLock()


def _path(name: str) -> Path:
    p = DATA_DIR / f"{name}.json"
    if not p.exists():
        default = DEFAULTS_DIR / f"{name}.json"
        if default.exists():
            shutil.copy(default, p)
        else:
            p.write_text("{}" if name == "settings" else "[]", encoding="utf-8")
    return p


def load(name: str) -> Any:
    with _lock:
        return json.loads(_path(name).read_text(encoding="utf-8"))


def save(name: str, data: Any) -> None:
    with _lock:
        tmp = _path(name).with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_path(name))


# ---------------------------------------------------------------- providers
def providers() -> list[dict]:
    return load("providers")


def enabled_providers() -> list[dict]:
    ps = [p for p in providers() if p.get("enabled") and p.get("model")]
    # A provider needs a key unless it's local (Ollama/LM Studio) or marked no_key
    ps = [p for p in ps if p.get("api_key") or p.get("no_key")]
    return sorted(ps, key=lambda p: p.get("priority", 99))


def get_provider(pid: str) -> dict | None:
    return next((p for p in providers() if p["id"] == pid), None)


def upsert_provider(data: dict) -> dict:
    ps = providers()
    pid = data.get("id")
    existing = next((p for p in ps if p["id"] == pid), None) if pid else None
    if existing:
        # Masked key from the UI means "keep the old one"
        if data.get("api_key", "").startswith("••••"):
            data["api_key"] = existing.get("api_key", "")
        existing.update(data)
        result = existing
    else:
        data["id"] = pid or uuid.uuid4().hex[:8]
        data.setdefault("enabled", True)
        data.setdefault("priority", len(ps) + 1)
        ps.append(data)
        result = data
    save("providers", ps)
    return result


def delete_provider(pid: str) -> None:
    save("providers", [p for p in providers() if p["id"] != pid])


def public_provider(p: dict) -> dict:
    """Provider dict safe to send to the browser (API key masked)."""
    out = dict(p)
    key = out.get("api_key", "")
    out["api_key"] = ("••••" + key[-4:]) if key else ""
    out["has_key"] = bool(key)
    return out


# ------------------------------------------------------------ personalities
def personalities() -> list[dict]:
    return load("personalities")


def get_personality(pid: str) -> dict:
    ps = personalities()
    return next((p for p in ps if p["id"] == pid), ps[0])


def upsert_personality(data: dict) -> dict:
    ps = personalities()
    existing = next((p for p in ps if p["id"] == data.get("id")), None)
    if existing:
        existing.update(data)
        result = existing
    else:
        data["id"] = data.get("id") or uuid.uuid4().hex[:8]
        ps.append(data)
        result = data
    save("personalities", ps)
    return result


def delete_personality(pid: str) -> None:
    save("personalities", [p for p in personalities() if p["id"] != pid])


# ----------------------------------------------------------------- settings
DEFAULT_SETTINGS = {
    "assistant_name": "JIM",
    "user_name": "",
    "personality": "jim",
    "mode": "auto",              # auto | single | council | race
    "single_provider": "",
    "council_size": 3,
    "synthesizer": "",           # provider id used to merge council answers ("" = first enabled)
    "temperature": 0.7,
    "max_tokens": 1024,
    "allow_system_control": True,
    "allow_shell": False,        # arbitrary shell commands (always asks to confirm)
    "confirm_risky": True,       # shutdown / restart / kill / shell need a click to confirm
    "stt_engine": "browser",     # browser | whisper
    "whisper_model": "base",
    "tts_enabled": True,
    "tts_voice": "",
    "tts_rate": 1.0,
    "tts_pitch": 1.0,
    "wake_word": "jim",
    "wake_word_enabled": False,
    "history_turns": 12,
}


def settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    s.update(load("settings") or {})
    return s


def update_settings(patch: dict) -> dict:
    s = settings()
    s.update({k: v for k, v in patch.items() if k in DEFAULT_SETTINGS})
    save("settings", s)
    return s
