#!/usr/bin/env python3
"""Start JIM.

    python run.py                 # local only, opens your browser
    python run.py --lan           # reachable from your phone on the same Wi-Fi (token protected)
    python run.py --port 8800 --no-browser
"""
import argparse
import os
import secrets
import socket
import threading
import time
import webbrowser


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser(description="JIM local AI assistant")
    ap.add_argument("--port", type=int, default=int(os.environ.get("JIM_PORT", 8765)))
    ap.add_argument("--lan", action="store_true", help="listen on your local network (requires access token)")
    ap.add_argument("--token", default=os.environ.get("JIM_TOKEN", ""), help="access token for --lan mode")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--allow-origin", action="append", default=[], metavar="URL",
                    help="extra website allowed to use this server (GitHub Pages UI is allowed already)")
    ap.add_argument("--dry-run", action="store_true", help="log system actions instead of performing them")
    a = ap.parse_args()

    host = "127.0.0.1"
    if a.lan:
        host = "0.0.0.0"
        os.environ["JIM_LAN"] = "1"
        os.environ["JIM_TOKEN"] = a.token or secrets.token_urlsafe(12)
    if a.allow_origin:
        os.environ["JIM_ALLOWED_ORIGINS"] = ",".join(a.allow_origin)
    if a.dry_run:
        os.environ["JIM_DRY_RUN"] = "1"

    import uvicorn  # imported after env is set so the server sees it

    url = f"http://localhost:{a.port}"
    print("\n  ┌──────────────────────────────────────────┐")
    print("  │   J.I.M  ·  local multi-LLM assistant     │")
    print("  └──────────────────────────────────────────┘")
    print(f"  Open:  {url}")
    print("    or:  https://amaljith75.github.io/jim  (same app, hosted on GitHub)")
    if a.lan:
        tok = os.environ["JIM_TOKEN"]
        print(f"  Phone: http://{lan_ip()}:{a.port}/?token={tok}")
        print("  (Voice input on phones needs HTTPS; typing works everywhere.)")
    print("  Stop:  Ctrl+C\n")

    if not a.no_browser:
        threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(url)), daemon=True).start()
    uvicorn.run("jim.server:app", host=host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
