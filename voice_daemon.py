#!/usr/bin/env python3
"""Always-on, hands-free JIM - no browser needed.

Listens to your microphone in the background. Say "Jim, open Spotify" or
"Hey Jim, what's the weather like on Mars?" and it answers out loud.

    pip install -r requirements-voice.txt
    python run.py --no-browser      # in one terminal (the brain)
    python voice_daemon.py          # in another (the ears and mouth)

Options:
    --engine whisper   offline speech recognition (default)
    --engine google    free online recognition (lighter on CPU)
    --model small      whisper size: tiny | base | small | medium
    --no-wake          respond to everything (no need to say "Jim")
"""
import argparse
import io
import re
import sys
import time

import httpx

API = "http://127.0.0.1:8765"


def speak_factory():
    import pyttsx3
    engine = pyttsx3.init()

    def speak(text: str, rate: float = 1.0):
        text = re.sub(r"```.*?```", " (code shown on screen) ", text, flags=re.S)
        text = re.sub(r"[*_#`>\[\]]", "", text)
        engine.setProperty("rate", int(185 * rate))
        engine.say(text[:900])
        engine.runAndWait()
    return speak


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["whisper", "google"], default="whisper")
    ap.add_argument("--model", default="base")
    ap.add_argument("--no-wake", action="store_true")
    ap.add_argument("--api", default=API)
    ap.add_argument("--token", default="")
    a = ap.parse_args()

    try:
        import speech_recognition as sr
    except ImportError:
        sys.exit("Install voice extras first:  pip install -r requirements-voice.txt")

    headers = {"x-jim-token": a.token} if a.token else {}
    try:
        st = httpx.get(f"{a.api}/api/state", headers=headers, timeout=5).json()
    except Exception:
        sys.exit(f"JIM server isn't running at {a.api}. Start it with:  python run.py")
    s = st["settings"]
    wake = s.get("wake_word", "jim").lower()
    per = next((p for p in st["personalities"] if p["id"] == s["personality"]), {})
    rate = float(per.get("tts_rate", 1.0))

    speak = speak_factory()
    whisper = None
    if a.engine == "whisper":
        from faster_whisper import WhisperModel
        print(f"Loading Whisper '{a.model}' (first run downloads it)…")
        whisper = WhisperModel(a.model, device="auto", compute_type="int8")

    rec = sr.Recognizer()
    rec.pause_threshold = 0.7
    rec.dynamic_energy_threshold = True
    mic = sr.Microphone()
    with mic as source:
        print("Calibrating mic for background noise…")
        rec.adjust_for_ambient_noise(source, duration=1.2)

    cid = None
    awake_until = 0.0
    speak(f"{s.get('assistant_name', 'JIM')} online.", rate)
    print(f"Listening. Say '{wake.title()}, …'  (Ctrl+C to quit)")

    wake_rx = re.compile(rf"^\s*(?:hey|hi|ok|okay)?\s*,?\s*{re.escape(wake)}\b[\s,.!:]*", re.I)
    while True:
        try:
            with mic as source:
                audio = rec.listen(source, phrase_time_limit=12)
            if whisper:
                wav = io.BytesIO(audio.get_wav_data(convert_rate=16000))
                segs, _ = whisper.transcribe(wav, vad_filter=True, language=None)
                heard = " ".join(x.text for x in segs).strip()
            else:
                heard = rec.recognize_google(audio)
        except sr.UnknownValueError:
            continue
        except KeyboardInterrupt:
            print("\nBye.")
            return
        except Exception as e:
            print("mic error:", e)
            time.sleep(1)
            continue
        if not heard:
            continue

        has_wake = bool(wake_rx.match(heard))
        if not (a.no_wake or has_wake or time.time() < awake_until):
            continue
        command = wake_rx.sub("", heard).strip()
        if not command:                      # just "Jim?" -> listen for the follow-up
            speak("Yes?", rate)
            awake_until = time.time() + 8
            continue

        print(f"you › {command}")
        try:
            r = httpx.post(f"{a.api}/api/chat/sync", headers=headers, timeout=180,
                           json={"message": command, "conversation_id": cid}).json()
        except Exception as e:
            speak("I lost connection to my brain.", rate)
            print("error:", e)
            continue
        cid = r.get("conversation_id") or cid
        for act in r.get("actions", []):
            if act.get("needs_confirm"):
                print("  ! needs confirmation in the web UI:", act["message"])
        print(f"jim › {r['text']}\n")
        if r.get("text"):
            speak(r["text"], rate)
        awake_until = time.time() + 10       # follow-ups don't need the wake word for 10 s


if __name__ == "__main__":
    main()
