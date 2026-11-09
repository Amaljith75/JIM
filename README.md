# J.I.M: your local multi-model AI assistant

JIM runs on your own computer. It combines several free LLMs into one assistant, talks and listens, and can control your computer: open apps, switch browser tabs, change the volume, search, take screenshots and more. You choose its personality.

```
 you (voice / text) ─► JIM server (your PC) ─┬─► instant commands  → opens apps, tabs, volume… in ~10 ms
                                             └─► LLM brain ─┬─ Ollama (offline)
                                                            ├─ Groq      ┐
                                                            ├─ Gemini    │ combined with
                                                            ├─ Cerebras  │ Auto / Council / Race
                                                            ├─ OpenRouter│
                                                            └─ + any model you add
```

## Open JIM

**Web app:** **https://amaljith75.github.io/jim**

The page is hosted on GitHub, but JIM's brain runs on your own computer. That's what lets it open apps, hear you and keep your keys private. Start the JIM server once (see below) and the web app connects to it automatically. The first time, Chrome asks to let the site *access devices on your local network*. Click **Allow**.

You can also skip GitHub entirely and open **http://localhost:8765**, which serves the same app.

## 1. Install (5 minutes)

1. Install **Python 3.10+** from python.org. On Windows, tick "Add Python to PATH".
2. Unzip JIM anywhere.
3. Start it:
   * **Windows:** double-click `scripts\start-windows.bat`
   * **macOS / Linux:** `./scripts/start-mac-linux.sh`
   * or by hand: `pip install -r requirements.txt` then `python run.py`
4. Your browser opens **http://localhost:8765**. You can also use **https://amaljith75.github.io/jim**. Use **Chrome or Edge** for voice.

## 2. Give JIM a brain (free)

Open **⚙ Settings → Models**. Paste a key into any card, click **Save**, then **Test**. Each card has a **get key ↗** link.

| Provider | Why | Key |
|---|---|---|
| **Ollama** | 100% offline, private, no key | Install from [ollama.com](https://ollama.com), then run `ollama pull llama3.2` (or `qwen2.5:7b`) |
| **Groq** | Very fast | [console.groq.com/keys](https://console.groq.com/keys) |
| **Google Gemini** | Smart, big context | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| **Cerebras** | Extremely fast | [cloud.cerebras.ai](https://cloud.cerebras.ai) |
| **OpenRouter** | Dozens of `:free` models behind one key | [openrouter.ai/keys](https://openrouter.ai/keys) |
| **Mistral** | Free "Experiment" plan | [console.mistral.ai](https://console.mistral.ai/api-keys) |

Free model IDs change often. If a test fails with "model not found", click **Fetch models** and pick one from the list. Free models are the ones ending in `:free` on OpenRouter.

**Adding any other LLM:** go to the bottom of the Models tab and choose **＋ Add a model**. Pick a preset (LM Studio, Hugging Face, NVIDIA, SambaNova, Together, DeepSeek, OpenAI…) or **Custom**. Paste the base URL, model ID and key. Any service with an OpenAI-compatible `/v1/chat/completions` endpoint works.

### How models are combined (top bar)

| Mode | What happens | Use for |
|---|---|---|
| ⚡ **Auto** (default) | Tries models in priority order. If one fails or hits its rate limit, it moves to the next. | Everyday use and voice |
| 🏛 **Council** | Asks 2–8 models in parallel, then a "merger" model writes one best answer from all of them. You can expand the drafts. | Hard questions, accuracy |
| 🏁 **Race** | Asks every model at once and uses the first answer back. | Lowest latency |
| 🎯 **Single** | Always uses the one model you pick. | Testing a model |

Priority (lower = tried first) is under **Advanced** on each card.

## 3. Voice

* **Talk:** click the mic or the orb, or press **Ctrl+Space**. **Esc** stops JIM talking.
* **Wake word:** turn on *Wake word "Jim"* and say "Jim, open Spotify" or "Hey Jim, what's a PID loop?". After JIM answers, you have 10 seconds to give a follow-up without saying "Jim". If you say only "Jim", it answers "Yes?" and waits.
* **Voice replies** reads answers aloud as they stream in. Each personality has its own speed and pitch. Choose the voice in **Settings → Voice**.
* **Offline speech:** run `pip install -r requirements-voice.txt`, then in **Settings → Voice** set *Speech recognition* to **Whisper**. Speech is then transcribed on your PC.

### Hands-free mode (no browser needed)

```bash
pip install -r requirements-voice.txt
python run.py --no-browser        # terminal 1: the brain
python voice_daemon.py            # terminal 2: always listening, speaks replies
python voice_daemon.py --engine google --model small   # lighter / alternative options
```
On Windows, if PyAudio fails to install, use `pip install pipwin && pipwin install pyaudio`, or Python 3.11/3.12, which have prebuilt wheels.

## 4. Things you can say

These commands run instantly and don't use any LLM:

| Category | Examples |
|---|---|
| Apps | "open Spotify", "open Chrome and VS Code", "launch calculator", "close Spotify" |
| Browser tabs | "next tab", "previous tab", "go to tab 3", "third tab", "new tab", "close tab", "reopen closed tab", "refresh", "go back", "zoom in" |
| Windows | "switch window", "minimize", "maximize", "show desktop", "close window" |
| Web | "search for ESP32-C6 pinout", "play lofi on YouTube", "go to github.com", "open Gmail" |
| Media | "volume up", "louder", "mute", "pause", "next song" |
| Keyboard | "type hello world", "press ctrl+s", "scroll down" |
| System | "take a screenshot", "lock the screen", "how's my battery", "what time is it", "set a timer for 10 minutes" |
| Memory | "remember that my robot is called Rover", "forget Rover" |
| Power (asks first) | "shut down", "restart", "sleep" |

Commands can be chained: "open chrome **and then** go to youtube". Anything else goes to the LLMs, and they can use the same tools. For example: "Open Notepad and write me a shopping list".

## 5. Personalities

Pick one from the top bar: **JIM (Classic butler)**, **Professional**, **Buddy**, **Sarcastic**, **Teacher**, **Hype Coach**, **Zen**, **Robotics Engineer**. To create your own, go to **Settings → Personalities → ＋ New**. Describe how JIM should behave, then set its voice speed and pitch.

## 6. Safety & privacy

* By default JIM listens only on `localhost`, so nothing on your network can reach it.
* Only two web pages may talk to your JIM server: its own page (`localhost:8765`) and `https://amaljith75.github.io`. The server blocks requests from every other website, disguised form posts, and DNS-rebinding tricks. To allow another site, start JIM with `python run.py --allow-origin https://your.site`.
* Your API keys stay in `data/providers.json` on your PC. The browser only sees the last 4 characters.
* Shutdown, restart, sleep and shell commands need a **Yes, do it** click. Shell commands are **off** by default (Settings → System).
* Turning off **Allow JIM to control this computer** makes JIM a chat-only assistant.
* Cloud models (Groq, Gemini…) receive what you send them, and some free tiers may train on prompts. Use **Ollama** with **Single** mode for fully private chats.
* `python run.py --dry-run` simulates every action without touching your PC, which is good for testing.

## 7. Use JIM from your phone

```bash
python run.py --lan
```
This prints a link such as `http://192.168.1.20:8765/?token=…`. Open it on your phone while on the same Wi-Fi. The token keeps other devices out. Typing works everywhere. Phone browsers only allow the microphone on HTTPS pages, so put JIM behind something like Tailscale or Caddy if you want voice on your phone.

## 8. API (for scripts, Arduino/ESP32, shortcuts)

```bash
curl -X POST http://localhost:8765/api/chat/sync -H "Content-Type: application/json" \
     -d '{"message":"open spotify"}'
# → {"text":"Opening Spotify.","actions":[...],"provider":"Instant command"}
```
Interactive docs: http://localhost:8765/api/docs. In `--lan` mode, add the header `x-jim-token: <token>`.

## Project layout

```
run.py              start the server
voice_daemon.py     hands-free background listener (optional)
jim/server.py       FastAPI routes
jim/orchestrator.py combines LLMs (auto / council / race / single) and runs actions
jim/llm.py          one OpenAI-compatible client for every provider
jim/actions.py      41 system-control tools (Windows / macOS / Linux)
jim/intents.py      instant voice-command parser
jim/memory.py       chat history + remembered facts (SQLite)
web/                the interface (plain HTML/CSS/JS) — also deployed to GitHub Pages
.github/workflows/  auto-deploys web/ to GitHub Pages on every push
config/             default providers + personalities (copied to data/ on first run)
data/               YOUR keys, settings, chats - back this up, never share it
```

**Adding a new tool:** in `jim/actions.py`, write a function and decorate it with `@tool("what it does", {"arg": "description"})`. The LLMs see it automatically. To make it instant, add a regex rule in `jim/intents.py`.

## Troubleshooting

* **"can't connect to localhost:11434"**: Ollama isn't running. Start it, or turn its card off.
* **HTTP 429**: that free tier is rate-limited. Auto mode already falls through to the next model, so add more providers.
* **HTTP 404 / model not found**: the free model was retired. Click **Fetch models** and pick a new one.
* **Mic does nothing**: use Chrome or Edge and allow microphone access. Open the page through `localhost` or the GitHub link, not an IP address.
* **GitHub web app says "JIM isn't running"**: first check that the start script's window is open. Then allow *local network access* for the site: click the icon left of the address bar → Site settings → Local network access → Allow. Brave blocks this by default, so use Chrome or Edge, or open http://localhost:8765 directly.
* **Keys/tabs don't work on Linux**: pyautogui needs an X11 session. On Wayland, log in with "Ubuntu on Xorg".
* **macOS**: allow your terminal under System Settings → Privacy & Security → **Accessibility** and **Microphone**.
