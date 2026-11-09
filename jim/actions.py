"""System control for JIM - works on Windows, macOS and Linux.

Every tool is a plain function registered with @tool. The LLM sees the list of
tools in its system prompt and asks for one with an action tag; the fast voice
command parser (intents.py) calls them directly.

Set JIM_DRY_RUN=1 to log actions without touching the computer (useful for testing).
"""
from __future__ import annotations

import datetime as _dt
import glob
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Callable

from . import config, memory

OS = "win" if sys.platform.startswith("win") else "mac" if sys.platform == "darwin" else "linux"
MOD = "command" if OS == "mac" else "ctrl"
DRY_RUN = os.environ.get("JIM_DRY_RUN") == "1"
HOME = Path.home()

TOOLS: dict[str, dict] = {}


def tool(description: str, args: dict[str, str] | None = None, risky: bool = False):
    def deco(fn: Callable):
        TOOLS[fn.__name__] = {"fn": fn, "description": description, "args": args or {}, "risky": risky}
        return fn
    return deco


class ActionError(Exception):
    pass


# --------------------------------------------------------------- helpers
def _gui():
    """Import pyautogui lazily (it needs a desktop session)."""
    try:
        import pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05
        return pyautogui
    except Exception as e:  # pragma: no cover - depends on desktop
        raise ActionError(f"Keyboard/mouse control unavailable ({e}). Install pyautogui and run JIM on your desktop session.")


def _keys(*combo: str):
    if DRY_RUN:
        return
    _gui().hotkey(*combo)


def _press(key: str, times: int = 1):
    if DRY_RUN:
        return
    _gui().press(key, presses=times, interval=0.03)


def _spawn(cmd, shell=False):
    if DRY_RUN:
        return
    kwargs: dict[str, Any] = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "shell": shell}
    if OS == "win":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)


def _startfile(target: str):
    if DRY_RUN:
        return
    if OS == "win":
        os.startfile(target)  # type: ignore[attr-defined]
    elif OS == "mac":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _open_url(url: str):
    if DRY_RUN:
        return
    webbrowser.open(url, new=2)


def _norm(s: str) -> str:
    return " ".join(s.lower().replace(".exe", "").replace(".app", "").split())


# ------------------------------------------------------------ app tables
# name -> {os: command / app name / URI}. Anything not listed is found by
# searching PATH, the Start Menu (Windows), /Applications (macOS) or .desktop files (Linux).
APPS: dict[str, dict[str, str]] = {
    "chrome":        {"win": "chrome", "mac": "Google Chrome", "linux": "google-chrome"},
    "firefox":       {"win": "firefox", "mac": "Firefox", "linux": "firefox"},
    "edge":          {"win": "msedge", "mac": "Microsoft Edge", "linux": "microsoft-edge"},
    "brave":         {"win": "brave", "mac": "Brave Browser", "linux": "brave-browser"},
    "vscode":        {"win": "code", "mac": "Visual Studio Code", "linux": "code"},
    "notepad":       {"win": "notepad", "mac": "TextEdit", "linux": "gedit"},
    "calculator":    {"win": "calc", "mac": "Calculator", "linux": "gnome-calculator"},
    "files":         {"win": "explorer", "mac": "Finder", "linux": "nautilus"},
    "terminal":      {"win": "wt", "mac": "Terminal", "linux": "x-terminal-emulator"},
    "cmd":           {"win": "cmd", "mac": "Terminal", "linux": "x-terminal-emulator"},
    "powershell":    {"win": "powershell", "mac": "Terminal", "linux": "x-terminal-emulator"},
    "settings":      {"win": "ms-settings:", "mac": "System Settings", "linux": "gnome-control-center"},
    "task manager":  {"win": "taskmgr", "mac": "Activity Monitor", "linux": "gnome-system-monitor"},
    "paint":         {"win": "mspaint", "mac": "Preview", "linux": "pinta"},
    "camera":        {"win": "microsoft.windows.camera:", "mac": "Photo Booth", "linux": "cheese"},
    "spotify":       {"win": "spotify:", "mac": "Spotify", "linux": "spotify"},
    "whatsapp":      {"win": "whatsapp:", "mac": "WhatsApp", "linux": "https://web.whatsapp.com"},
    "telegram":      {"win": "tg:", "mac": "Telegram", "linux": "telegram-desktop"},
    "discord":       {"win": "discord:", "mac": "Discord", "linux": "discord"},
    "word":          {"win": "winword", "mac": "Microsoft Word", "linux": "libreoffice --writer"},
    "excel":         {"win": "excel", "mac": "Microsoft Excel", "linux": "libreoffice --calc"},
    "powerpoint":    {"win": "powerpnt", "mac": "Microsoft PowerPoint", "linux": "libreoffice --impress"},
    "vlc":           {"win": "vlc", "mac": "VLC", "linux": "vlc"},
    "obs":           {"win": "obs64", "mac": "OBS", "linux": "obs"},
    "arduino":       {"win": "Arduino IDE", "mac": "Arduino IDE", "linux": "arduino-ide"},
    "mail":          {"win": "outlookmail:", "mac": "Mail", "linux": "thunderbird"},
    "clock":         {"win": "ms-clock:", "mac": "Clock", "linux": "gnome-clocks"},
}

ALIASES = {
    "google chrome": "chrome", "browser": "chrome", "microsoft edge": "edge",
    "vs code": "vscode", "visual studio code": "vscode", "code": "vscode",
    "text editor": "notepad", "calc": "calculator",
    "file explorer": "files", "explorer": "files", "file manager": "files", "finder": "files", "my files": "files",
    "command prompt": "cmd", "shell": "terminal", "console": "terminal",
    "control panel": "settings", "system settings": "settings", "preferences": "settings",
    "activity monitor": "task manager", "system monitor": "task manager",
    "microsoft word": "word", "ms word": "word", "microsoft excel": "excel", "ms excel": "excel",
    "microsoft powerpoint": "powerpoint", "ppt": "powerpoint", "obs studio": "obs",
    "arduino ide": "arduino", "outlook": "mail", "email": "mail", "alarms": "clock",
}

WEBSITES = {
    "youtube": "https://www.youtube.com", "gmail": "https://mail.google.com", "google": "https://www.google.com",
    "github": "https://github.com", "chatgpt": "https://chat.openai.com", "claude": "https://claude.ai",
    "netflix": "https://www.netflix.com", "instagram": "https://www.instagram.com", "facebook": "https://www.facebook.com",
    "twitter": "https://x.com", "x": "https://x.com", "linkedin": "https://www.linkedin.com",
    "reddit": "https://www.reddit.com", "amazon": "https://www.amazon.in", "flipkart": "https://www.flipkart.com",
    "google drive": "https://drive.google.com", "drive": "https://drive.google.com", "maps": "https://maps.google.com",
    "google maps": "https://maps.google.com", "calendar": "https://calendar.google.com", "wikipedia": "https://wikipedia.org",
    "stack overflow": "https://stackoverflow.com", "hotstar": "https://www.hotstar.com", "prime video": "https://www.primevideo.com",
}

PROCESS_NAMES = {
    "chrome": ["chrome", "google chrome"], "firefox": ["firefox"], "edge": ["msedge", "microsoft edge"],
    "brave": ["brave"], "vscode": ["code", "electron"], "notepad": ["notepad", "textedit", "gedit"],
    "calculator": ["calculator", "calc", "gnome-calculator", "calculatorapp"], "spotify": ["spotify"],
    "whatsapp": ["whatsapp"], "telegram": ["telegram"], "discord": ["discord"], "word": ["winword", "microsoft word"],
    "excel": ["excel", "microsoft excel"], "powerpoint": ["powerpnt", "microsoft powerpoint"], "vlc": ["vlc"],
    "obs": ["obs", "obs64"], "paint": ["mspaint"], "task manager": ["taskmgr"],
}


def canonical_app(name: str) -> str:
    n = _norm(name)
    return ALIASES.get(n, n)


def _find_windows_shortcut(name: str) -> str | None:
    dirs = [
        os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
        str(HOME / "Desktop"), os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Desktop"),
    ]
    n = _norm(name)
    best = None
    for d in dirs:
        for f in glob.glob(os.path.join(d, "**", "*.lnk"), recursive=True) + glob.glob(os.path.join(d, "**", "*.url"), recursive=True):
            stem = _norm(Path(f).stem)
            if stem == n:
                return f
            if n in stem and "uninstall" not in stem and (best is None or len(stem) < len(_norm(Path(best).stem))):
                best = f
    return best


def _find_linux_desktop(name: str) -> str | None:
    dirs = ["/usr/share/applications", "/usr/local/share/applications", str(HOME / ".local/share/applications"),
            "/var/lib/flatpak/exports/share/applications", str(HOME / ".local/share/flatpak/exports/share/applications"),
            "/var/lib/snapd/desktop/applications"]
    n = _norm(name)
    for d in dirs:
        for f in glob.glob(os.path.join(d, "*.desktop")):
            try:
                text = Path(f).read_text(errors="ignore")
            except OSError:
                continue
            for line in text.splitlines():
                if line.startswith("Name="):
                    if n in _norm(line[5:]):
                        return f
                    break
    return None


def _find_mac_app(name: str) -> str | None:
    n = _norm(name)
    for d in ["/Applications", "/System/Applications", "/System/Applications/Utilities", str(HOME / "Applications")]:
        for f in glob.glob(os.path.join(d, "*.app")):
            if n in _norm(Path(f).stem):
                return f
    return None


# ================================================================= TOOLS
# ---------------------------------------------------------------- apps
@tool("Open/launch an application or a well-known website by name", {"name": "app name e.g. spotify, chrome, vscode, calculator"})
def open_app(name: str) -> str:
    key = canonical_app(name)
    pretty = name.strip().title()

    if key in WEBSITES and key not in APPS:
        _open_url(WEBSITES[key])
        return f"Opening {pretty}."

    target = APPS.get(key, {}).get(OS, name.strip())

    if target.startswith(("http://", "https://")):
        _open_url(target)
        return f"Opening {pretty}."

    if OS == "win":
        if target.endswith(":"):                         # protocol URI e.g. spotify:
            _startfile(target)
            return f"Opening {pretty}."
        exe = shutil.which(target)
        if exe:
            _spawn([exe])
            return f"Opening {pretty}."
        lnk = _find_windows_shortcut(target) or _find_windows_shortcut(name)
        if lnk:
            _startfile(lnk)
            return f"Opening {pretty}."
        # `start` resolves App Paths registry entries (chrome, winword, excel...)
        if not DRY_RUN:
            r = subprocess.run(f'start "" "{target}"', shell=True, capture_output=True)
            if r.returncode == 0:
                return f"Opening {pretty}."
    elif OS == "mac":
        app = _find_mac_app(target) or _find_mac_app(name)
        if DRY_RUN:
            return f"Opening {pretty}."
        r = subprocess.run(["open", "-a", app or target], capture_output=True)
        if r.returncode == 0:
            return f"Opening {pretty}."
    else:
        parts = target.split()
        if shutil.which(parts[0]):
            _spawn(parts)
            return f"Opening {pretty}."
        desktop = _find_linux_desktop(target) or _find_linux_desktop(name)
        if desktop:
            if shutil.which("gtk-launch"):
                _spawn(["gtk-launch", Path(desktop).stem])
            else:
                _spawn(["gio", "launch", desktop])
            return f"Opening {pretty}."

    if key in WEBSITES:
        _open_url(WEBSITES[key])
        return f"Opening {pretty} in your browser."
    raise ActionError(f"I couldn't find an app called '{name}' on this computer.")


@tool("Close/quit a running application", {"name": "app name"})
def close_app(name: str) -> str:
    import psutil
    key = canonical_app(name)
    needles = PROCESS_NAMES.get(key, [key])
    killed = 0
    me = os.getpid()
    for proc in psutil.process_iter(["name", "pid"]):
        pname = _norm(proc.info.get("name") or "")
        if proc.info["pid"] == me or not pname:
            continue
        if any(nd == pname or pname.startswith(nd) for nd in needles):
            if not DRY_RUN:
                try:
                    proc.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            killed += 1
    if killed or DRY_RUN:
        return f"Closed {name.strip().title()}."
    raise ActionError(f"{name.strip().title()} doesn't seem to be running.")


@tool("Open a folder in the file manager", {"path": "folder path or: downloads, documents, desktop, pictures, music, videos, home"})
def open_folder(path: str = "home") -> str:
    known = {"downloads": "Downloads", "documents": "Documents", "desktop": "Desktop", "pictures": "Pictures",
             "photos": "Pictures", "music": "Music", "videos": "Videos", "home": ""}
    p = path.strip().lower().removesuffix(" folder")
    folder = HOME / known[p] if p in known else Path(os.path.expanduser(path.strip()))
    if not folder.exists():
        raise ActionError(f"Folder not found: {folder}")
    _startfile(str(folder))
    return f"Opening {folder.name or 'your home folder'}."


# ------------------------------------------------------------- browser
@tool("Open a website URL in the default browser", {"url": "full or partial URL"})
def open_url(url: str) -> str:
    u = url.strip()
    key = u.lower()
    if key in WEBSITES:
        u = WEBSITES[key]
    elif not u.startswith(("http://", "https://")):
        u = "https://" + (u if "." in u else u + ".com")
    _open_url(u)
    return f"Opening {urllib.parse.urlparse(u).netloc}."


@tool("Search the web with Google", {"query": "search text"})
def web_search(query: str) -> str:
    _open_url("https://www.google.com/search?q=" + urllib.parse.quote_plus(query))
    return f"Searching for {query}."


@tool("Search YouTube (opens results)", {"query": "what to search on YouTube"})
def youtube(query: str) -> str:
    _open_url("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query))
    return f"Here's {query} on YouTube."


@tool("Switch to the next browser tab")
def next_tab() -> str:
    _keys("ctrl", "tab")
    return "Next tab."


@tool("Switch to the previous browser tab")
def previous_tab() -> str:
    _keys("ctrl", "shift", "tab")
    return "Previous tab."


@tool("Go to browser tab number N (1-8, 9 = last tab)", {"number": "tab number"})
def go_to_tab(number: int = 1) -> str:
    n = max(1, min(9, int(number)))
    _keys(MOD, str(n))
    return f"Tab {n}." if n < 9 else "Last tab."


@tool("Open a new browser tab")
def new_tab() -> str:
    _keys(MOD, "t")
    return "New tab open."


@tool("Close the current browser tab")
def close_tab() -> str:
    _keys(MOD, "w")
    return "Tab closed."


@tool("Reopen the last closed browser tab")
def reopen_tab() -> str:
    _keys(MOD, "shift", "t")
    return "Tab restored."


@tool("Refresh/reload the current page")
def refresh() -> str:
    _keys(MOD, "r")
    return "Refreshed."


@tool("Go back in the browser")
def go_back() -> str:
    _keys("alt", "left") if OS != "mac" else _keys("command", "[")
    return "Going back."


@tool("Go forward in the browser")
def go_forward() -> str:
    _keys("alt", "right") if OS != "mac" else _keys("command", "]")
    return "Going forward."


@tool("Zoom in, zoom out or reset zoom", {"direction": "in | out | reset"})
def zoom(direction: str = "in") -> str:
    d = direction.lower()
    _keys(MOD, {"in": "+", "out": "-", "reset": "0"}.get(d, "+"))
    return f"Zoom {d}."


# ------------------------------------------------------------- windows
@tool("Switch to the next open window (Alt+Tab)")
def switch_window() -> str:
    _keys("command", "tab") if OS == "mac" else _keys("alt", "tab")
    return "Switched window."


@tool("Minimize the current window")
def minimize_window() -> str:
    _keys("command", "m") if OS == "mac" else _keys("win", "down") if OS == "win" else _keys("super", "h")
    return "Minimized."


@tool("Maximize the current window")
def maximize_window() -> str:
    if OS == "mac":
        _keys("ctrl", "command", "f")
    elif OS == "win":
        _keys("win", "up")
    else:
        _keys("super", "up")
    return "Maximized."


@tool("Close the current window")
def close_window() -> str:
    _keys("command", "w") if OS == "mac" else _keys("alt", "f4")
    return "Window closed."


@tool("Show the desktop / minimize everything")
def show_desktop() -> str:
    if OS == "win":
        _keys("win", "d")
    elif OS == "mac":
        _press("f11")
    else:
        _keys("ctrl", "super", "d")
    return "Here's your desktop."


# --------------------------------------------------------------- input
@tool("Type text at the cursor", {"text": "text to type"})
def type_text(text: str) -> str:
    if not DRY_RUN:
        _gui().write(text, interval=0.01)
    return "Typed it."


@tool("Press a key or key combination", {"keys": "e.g. enter, ctrl+c, alt+f4, ctrl+shift+esc"})
def press_keys(keys: str) -> str:
    combo = [k.strip().lower().replace("control", "ctrl").replace("cmd", "command") for k in keys.replace(" ", "+").split("+") if k.strip()]
    if not combo:
        raise ActionError("No keys given.")
    if len(combo) == 1:
        _press(combo[0])
    else:
        _keys(*combo)
    return f"Pressed {'+'.join(combo)}."


@tool("Scroll the page", {"direction": "up | down", "amount": "1-20 (default 5)"})
def scroll(direction: str = "down", amount: int = 5) -> str:
    if not DRY_RUN:
        _gui().scroll((1 if direction.lower().startswith("u") else -1) * int(amount) * 100)
    return f"Scrolling {direction}."


# --------------------------------------------------------------- media
def _volume_os(action: str, steps: int) -> bool:
    """Native volume control where pyautogui media keys are unreliable."""
    if DRY_RUN:
        return True
    if OS == "mac":
        script = {"up": f"set volume output volume ((output volume of (get volume settings)) + {steps * 6})",
                  "down": f"set volume output volume ((output volume of (get volume settings)) - {steps * 6})",
                  "mute": "set volume output muted not (output muted of (get volume settings))"}[action]
        return subprocess.run(["osascript", "-e", script]).returncode == 0
    if OS == "linux":
        if shutil.which("pactl"):
            arg = {"up": ["set-sink-volume", "@DEFAULT_SINK@", f"+{steps * 5}%"],
                   "down": ["set-sink-volume", "@DEFAULT_SINK@", f"-{steps * 5}%"],
                   "mute": ["set-sink-mute", "@DEFAULT_SINK@", "toggle"]}[action]
            return subprocess.run(["pactl", *arg]).returncode == 0
        if shutil.which("amixer"):
            arg = {"up": f"{steps * 5}%+", "down": f"{steps * 5}%-", "mute": "toggle"}[action]
            return subprocess.run(["amixer", "-q", "set", "Master", arg]).returncode == 0
    return False


@tool("Turn the volume up", {"steps": "how much, 1-10 (default 3)"})
def volume_up(steps: int = 3) -> str:
    if not _volume_os("up", int(steps)):
        _press("volumeup", int(steps) * 2)
    return "Volume up."


@tool("Turn the volume down", {"steps": "how much, 1-10 (default 3)"})
def volume_down(steps: int = 3) -> str:
    if not _volume_os("down", int(steps)):
        _press("volumedown", int(steps) * 2)
    return "Volume down."


@tool("Mute or unmute audio")
def mute() -> str:
    if not _volume_os("mute", 1):
        _press("volumemute")
    return "Toggled mute."


@tool("Play or pause media")
def play_pause() -> str:
    _press("playpause")
    return "Play/pause."


@tool("Skip to the next track")
def next_track() -> str:
    _press("nexttrack")
    return "Next track."


@tool("Go to the previous track")
def previous_track() -> str:
    _press("prevtrack")
    return "Previous track."


# -------------------------------------------------------------- system
@tool("Take a screenshot and save it to Pictures/JIM")
def screenshot() -> str:
    folder = HOME / "Pictures" / "JIM"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"screenshot_{_dt.datetime.now():%Y%m%d_%H%M%S}.png"
    if not DRY_RUN:
        _gui().screenshot(str(path))
    return f"Screenshot saved to {path}."


@tool("Report CPU, memory, disk and battery status")
def system_info() -> str:
    import psutil
    cpu = psutil.cpu_percent(interval=0.4)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(str(HOME.anchor or "/"))
    parts = [f"CPU at {cpu:.0f}%", f"memory {mem.percent:.0f}% used of {mem.total / 1e9:.1f} GB",
             f"disk {disk.percent:.0f}% full"]
    batt = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if batt:
        parts.append(f"battery {batt.percent:.0f}%{' and charging' if batt.power_plugged else ''}")
    return ", ".join(parts) + "."


@tool("Lock the computer screen")
def lock_screen() -> str:
    if DRY_RUN:
        return "Locking the screen."
    if OS == "win":
        subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
    elif OS == "mac":
        _keys("ctrl", "command", "q")
    else:
        for cmd in (["loginctl", "lock-session"], ["xdg-screensaver", "lock"], ["gnome-screensaver-command", "-l"]):
            if shutil.which(cmd[0]):
                subprocess.Popen(cmd)
                break
    return "Locking the screen."


@tool("Put the computer to sleep", risky=True)
def sleep_computer() -> str:
    if not DRY_RUN:
        if OS == "win":
            subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        elif OS == "mac":
            subprocess.Popen(["pmset", "sleepnow"])
        else:
            subprocess.Popen(["systemctl", "suspend"])
    return "Going to sleep."


@tool("Shut down the computer", risky=True)
def shutdown() -> str:
    if not DRY_RUN:
        cmd = {"win": ["shutdown", "/s", "/t", "10"], "mac": ["osascript", "-e", 'tell app "System Events" to shut down'],
               "linux": ["systemctl", "poweroff"]}[OS]
        subprocess.Popen(cmd)
    return "Shutting down. Goodbye."


@tool("Restart the computer", risky=True)
def restart() -> str:
    if not DRY_RUN:
        cmd = {"win": ["shutdown", "/r", "/t", "10"], "mac": ["osascript", "-e", 'tell app "System Events" to restart'],
               "linux": ["systemctl", "reboot"]}[OS]
        subprocess.Popen(cmd)
    return "Restarting."


@tool("Run a shell/terminal command and return its output (only if the user enabled shell access)", {"command": "the command"}, risky=True)
def run_command(command: str) -> str:
    if not config.settings().get("allow_shell"):
        raise ActionError("Shell commands are disabled. Turn on 'Allow shell commands' in Settings → System.")
    if DRY_RUN:
        return f"(dry run) {command}"
    r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
    out = (r.stdout or "") + (r.stderr or "")
    return (out.strip()[:1500] or f"Done (exit code {r.returncode}).")


# ----------------------------------------------------- client & memory
@tool("Set a countdown timer", {"seconds": "duration in seconds", "label": "optional name"})
def set_timer(seconds: int, label: str = "Timer") -> dict:
    s = int(seconds)
    human = f"{s // 60} minute{'s' if s // 60 != 1 else ''}" if s >= 60 and s % 60 == 0 else f"{s} seconds"
    return {"message": f"Timer set for {human}.", "client": {"timer": {"seconds": s, "label": label}}}


@tool("Remember a fact about the user for future chats", {"fact": "the fact to remember"})
def remember(fact: str) -> str:
    memory.add_fact(fact)
    return "Got it, I'll remember that."


@tool("Forget remembered facts matching some text", {"text": "text to match"})
def forget(text: str) -> str:
    n = memory.forget_facts(text)
    return f"Forgot {n} thing{'s' if n != 1 else ''}." if n else "I had nothing matching that."


@tool("Tell the current time and date")
def current_time() -> str:
    now = _dt.datetime.now()
    return now.strftime("It's %I:%M %p on %A, %d %B %Y.").replace(" 0", " ")


# ================================================================ runner
def run(name: str, args: dict | None = None, confirmed: bool = False) -> dict:
    """Execute a tool. Returns {ok, tool, message, needs_confirm?, client?}."""
    args = args or {}
    s = config.settings()
    t = TOOLS.get(name)
    if not t:
        return {"ok": False, "tool": name, "args": args, "message": f"Unknown action '{name}'."}
    if not s.get("allow_system_control") and name not in {"remember", "forget", "current_time", "set_timer"}:
        return {"ok": False, "tool": name, "args": args, "message": "System control is turned off in Settings."}
    if t["risky"] and s.get("confirm_risky", True) and not confirmed:
        return {"ok": False, "tool": name, "args": args, "needs_confirm": True,
                "message": f"Confirm: {t['description'].lower()}" + (f" → {args}" if args else "") + "?"}
    try:
        clean = {k: v for k, v in args.items() if k in t["args"]}
        result = t["fn"](**clean)
        if isinstance(result, dict):
            return {"ok": True, "tool": name, "args": args, **result}
        return {"ok": True, "tool": name, "args": args, "message": str(result)}
    except ActionError as e:
        return {"ok": False, "tool": name, "args": args, "message": str(e)}
    except TypeError as e:
        return {"ok": False, "tool": name, "args": args, "message": f"Bad arguments for {name}: {e}"}
    except Exception as e:  # never crash the server because of a desktop quirk
        return {"ok": False, "tool": name, "args": args, "message": f"{name} failed: {type(e).__name__}: {e}"}


def tools_for_prompt() -> str:
    lines = []
    for name, t in TOOLS.items():
        arg = ", ".join(f'"{k}": {v}' for k, v in t["args"].items())
        lines.append(f"- {name}({arg}) — {t['description']}")
    return "\n".join(lines)


def tools_public() -> list[dict]:
    return [{"name": n, "description": t["description"], "args": t["args"], "risky": t["risky"]} for n, t in TOOLS.items()]


def platform_name() -> str:
    return f"{platform.system()} {platform.release()}"
