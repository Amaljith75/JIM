/* JIM web client — chat, voice, settings. No build step, no external libraries. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

// ------------------------------------------------------------------ API
const params = new URLSearchParams(location.search);
if (params.get("token")) { localStorage.setItem("jim_token", params.get("token")); history.replaceState(null, "", "/"); }
const TOKEN = localStorage.getItem("jim_token") || "";

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(TOKEN ? { "x-jim-token": TOKEN } : {}), ...(opts.headers || {}) };
  const r = await fetch(path, { ...opts, headers, body: opts.body && typeof opts.body !== "string" && !(opts.body instanceof Blob) ? JSON.stringify(opts.body) : opts.body });
  if (r.status === 401) { toast("Access token needed — open the link printed in the JIM terminal."); throw new Error("401"); }
  if (!r.ok && opts.raw !== true) throw new Error((await r.text()) || r.statusText);
  return opts.raw ? r : r.json();
}

// ---------------------------------------------------------------- state
let S = { settings: {}, personalities: [], providers: [], tools: [] };
let convId = null;
let busy = false;

function toast(msg, ms = 3200) {
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}
function setStatus(txt) { $("#status").textContent = txt; }
function setMood(m) { document.body.classList.remove("listening", "thinking", "speaking"); if (m) document.body.classList.add(m); }

async function loadState() {
  S = await api("/api/state");
  const s = S.settings;
  $("#brandName").textContent = (s.assistant_name || "JIM").split("").join(".");
  document.title = s.assistant_name || "JIM";
  $("#wakeLabel").textContent = cap(s.wake_word || "jim");
  $("#ttsToggle").checked = !!s.tts_enabled;
  $("#modeSel").value = s.mode || "auto";
  renderPersonaSelect(); renderSingleSelect(); renderModelCount();
  const hr = new Date().getHours();
  const greet = hr < 12 ? "Good morning" : hr < 17 ? "Good afternoon" : "Good evening";
  $("#welcomeTitle").textContent = `${greet}${s.user_name ? ", " + s.user_name : ""}. ${s.assistant_name || "JIM"} online.`;
}
const cap = (x) => x.charAt(0).toUpperCase() + x.slice(1);
const persona = () => S.personalities.find((p) => p.id === S.settings.personality) || S.personalities[0] || {};
const usable = () => S.providers.filter((p) => p.enabled && p.model && (p.has_key || p.no_key));

function renderPersonaSelect() {
  $("#personaSel").innerHTML = S.personalities.map((p) => `<option value="${p.id}">${p.emoji || ""} ${esc(p.name)}</option>`).join("");
  $("#personaSel").value = S.settings.personality;
}
function renderSingleSelect() {
  const u = usable();
  $("#singleSel").innerHTML = u.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("") || `<option value="">no models</option>`;
  if (S.settings.single_provider) $("#singleSel").value = S.settings.single_provider;
  $("#singleSel").classList.toggle("hidden", $("#modeSel").value !== "single");
}
function renderModelCount() {
  const n = usable().length;
  $("#modelCount").textContent = n ? `${n} model${n > 1 ? "s" : ""}` : "no models";
  $("#modelCount").style.color = n ? "" : "var(--warn)";
}
async function saveSettings(patch) { S.settings = await api("/api/settings", { method: "POST", body: patch }); }

$("#personaSel").onchange = async (e) => { await saveSettings({ personality: e.target.value }); toast(`${persona().emoji || ""} ${persona().name} mode`); };
$("#modeSel").onchange = async (e) => { await saveSettings({ mode: e.target.value }); renderSingleSelect(); };
$("#singleSel").onchange = async (e) => saveSettings({ single_provider: e.target.value });
$("#ttsToggle").onchange = async (e) => { await saveSettings({ tts_enabled: e.target.checked }); if (!e.target.checked) speechSynthesis.cancel(); };

// ------------------------------------------------------------- markdown
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function inline(s) {
  return s.replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
function md(src) {
  src = stripTags(src);
  const out = []; const parts = src.split(/```/);
  parts.forEach((part, i) => {
    if (i % 2) {
      const nl = part.indexOf("\n"); const code = nl >= 0 ? part.slice(nl + 1) : part;
      out.push(`<pre><button class="copy">copy</button><code>${esc(code.replace(/\n$/, ""))}</code></pre>`); return;
    }
    let html = ""; let list = null;
    for (const raw of esc(part).split("\n")) {
      const line = raw.trimEnd();
      const ul = line.match(/^\s*[-*•]\s+(.*)/), ol = line.match(/^\s*\d+[.)]\s+(.*)/), h = line.match(/^(#{1,3})\s+(.*)/);
      if (ul || ol) {
        const type = ul ? "ul" : "ol";
        if (list !== type) { if (list) html += `</${list}>`; html += `<${type}>`; list = type; }
        html += `<li>${inline((ul || ol)[1])}</li>`; continue;
      }
      if (list) { html += `</${list}>`; list = null; }
      if (h) html += `<h3>${inline(h[2])}</h3>`;
      else if (line.trim()) html += `<p>${inline(line)}</p>`;
    }
    if (list) html += `</${list}>`;
    out.push(html);
  });
  return out.join("");
}
// hide [[ACTION:{...}]] tags (also half-streamed ones)
function stripTags(t) { return t.replace(/\[\[ACTION:[\s\S]*?\]\]/g, "").replace(/\[\[ACTION:[\s\S]*$/, "").replace(/\[\[?A?C?T?I?O?N?:?$/, ""); }
function speakable(t) {
  return stripTags(t).replace(/```[\s\S]*?(```|$)/g, " ").replace(/`([^`]+)`/g, "$1").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[*_#>|]/g, "").replace(/https?:\/\/\S+/g, "link").replace(/\s+/g, " ").trim();
}

document.addEventListener("click", (e) => {
  if (e.target.classList.contains("copy")) {
    navigator.clipboard.writeText(e.target.nextElementSibling.textContent); e.target.textContent = "copied"; setTimeout(() => (e.target.textContent = "copy"), 1200);
  }
});

// ----------------------------------------------------------- messages UI
const msgs = $("#messages");
function scrollDown() { const c = $("#chat"); c.scrollTop = c.scrollHeight; }
function addMsg(role, html = "") {
  $("#welcome").classList.add("hidden");
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.innerHTML = `<div class="avatar">${role === "user" ? "🧑" : ""}</div><div class="bubble"><div class="body">${html}</div></div>`;
  msgs.appendChild(el); scrollDown(); return el;
}
function actionHTML(r) {
  if (r.needs_confirm) {
    return `<div class="action confirm" data-tool="${esc(r.tool)}" data-args='${esc(JSON.stringify(r.args || {}))}'>⚠️ <span class="grow">${esc(r.message)}</span>
      <button class="btn small primary" data-confirm>Yes, do it</button><button class="btn small" data-cancel>Cancel</button></div>`;
  }
  return `<div class="action ${r.ok ? "" : "fail"}">${r.ok ? "✅" : "❌"} <span class="grow">${esc(r.message)}</span><span class="tool">${esc(r.tool)}</span></div>`;
}
msgs.addEventListener("click", async (e) => {
  const box = e.target.closest(".action.confirm"); if (!box) return;
  if (e.target.hasAttribute("data-cancel")) { box.outerHTML = actionHTML({ ok: false, tool: box.dataset.tool, message: "Cancelled." }); return; }
  if (e.target.hasAttribute("data-confirm")) {
    const r = await api("/api/action", { method: "POST", body: { tool: box.dataset.tool, args: JSON.parse(box.dataset.args), confirmed: true } });
    box.outerHTML = actionHTML(r); handleClient(r); if (r.message) speak(r.message);
  }
});

// ------------------------------------------------------------------ chat
async function send(text, fromVoice = false) {
  text = (text || "").trim();
  if (!text || busy) return;
  busy = true; $("#sendBtn").disabled = true;
  $("#input").value = ""; autosize();
  speechSynthesis.cancel(); speaker.reset();
  addMsg("user", esc(text).replace(/\n/g, "<br>"));
  const bot = addMsg("bot", `<span class="cursor"></span>`);
  const body = $(".body", bot), bubble = $(".bubble", bot);
  let full = "", meta = null, notices = "", actionsBox = null, council = null, errored = false;
  setMood("thinking"); setStatus("Thinking…");
  const t0 = performance.now();

  try {
    const r = await api("/api/chat", { method: "POST", body: { message: text, conversation_id: convId }, raw: true });
    const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = "";
    while (true) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, i).trim(); buf = buf.slice(i + 2);
        if (!line.startsWith("data:")) continue;
        const ev = JSON.parse(line.slice(5));
        switch (ev.type) {
          case "conversation": if (convId !== ev.id) { convId = ev.id; loadConvs(); } break;
          case "meta": meta = ev; setStatus(`${ev.provider}…`); break;
          case "notice": notices += `<div class="notice">${esc(ev.text)}</div>`; body.innerHTML = notices + md(full) + `<span class="cursor"></span>`; break;
          case "token":
            if (!full) setMood(null);
            full += ev.text; body.innerHTML = notices + md(full) + `<span class="cursor"></span>`;
            if (S.settings.tts_enabled) speaker.feed(full);
            scrollDown(); break;
          case "council": council = ev.answers; break;
          case "action":
            if (!actionsBox) { actionsBox = document.createElement("div"); actionsBox.className = "actions"; bubble.appendChild(actionsBox); }
            actionsBox.insertAdjacentHTML("beforeend", actionHTML(ev.result)); handleClient(ev.result); scrollDown(); break;
          case "error": errored = true; body.innerHTML = notices + md(full) + `<div class="error">${esc(ev.text)}</div>`; break;
          case "done":
            if (!errored) body.innerHTML = notices + (md(ev.text || full) || (actionsBox ? "" : "<span class='muted'>(no reply)</span>"));
            if (S.settings.tts_enabled) speaker.finish(ev.text || full);
            break;
        }
      }
    }
  } catch (e) {
    body.innerHTML = `<div class="error">Couldn't reach JIM's server: ${esc(e.message)}</div>`;
  }

  if (council && council.length) {
    const d = document.createElement("details"); d.className = "council";
    d.innerHTML = `<summary>🏛 ${council.length} model drafts</summary>` + council.map((a) => `<div class="c-ans"><b>${esc(a.provider)}</b> <span class="muted small">${esc(a.model)}</span>${md(a.text)}</div>`).join("");
    bubble.appendChild(d);
  }
  const secs = ((performance.now() - t0) / 1000).toFixed(1);
  const m = document.createElement("div"); m.className = "meta";
  m.innerHTML = `<span>${meta ? esc(meta.provider) + (meta.model && meta.model !== "local" ? " · " + esc(meta.model) : "") : ""}</span><span>${secs}s</span><button title="Read aloud">🔊</button><button title="Copy">📋</button>`;
  m.children[2].onclick = () => speak(speakable(full), true);
  m.children[3].onclick = () => { navigator.clipboard.writeText(stripTags(full)); toast("Copied"); };
  bubble.appendChild(m);
  scrollDown();
  busy = false; $("#sendBtn").disabled = false;
  if (!document.body.classList.contains("speaking")) setMood(null);
  setStatus("Ready");
  if (!fromVoice) $("#input").focus();
}

function handleClient(r) {
  if (r && r.client && r.client.timer) startTimer(r.client.timer.seconds, r.client.timer.label);
}

// ---------------------------------------------------------------- timers
function startTimer(seconds, label = "Timer") {
  const el = document.createElement("div"); el.className = "timer";
  const end = Date.now() + seconds * 1000;
  el.innerHTML = `⏱ <span>${label}</span> <b></b><button title="Cancel">✕</button>`;
  $("#timers").appendChild(el);
  const tick = () => {
    const left = Math.max(0, Math.round((end - Date.now()) / 1000));
    $("b", el).textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
    if (left <= 0) {
      clearInterval(iv); beep(); speak(`${label} is done.`, true);
      if (Notification?.permission === "granted") new Notification("JIM", { body: `${label} is done!` });
      setTimeout(() => el.remove(), 8000);
    }
  };
  const iv = setInterval(tick, 500); tick();
  $("button", el).onclick = () => { clearInterval(iv); el.remove(); };
  if (window.Notification && Notification.permission === "default") Notification.requestPermission();
}
function beep() {
  try {
    const ctx = new AudioContext();
    [0, 0.35, 0.7].forEach((t) => {
      const o = ctx.createOscillator(), g = ctx.createGain(); o.frequency.value = 880; o.connect(g); g.connect(ctx.destination);
      g.gain.setValueAtTime(0.25, ctx.currentTime + t); g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + t + 0.3);
      o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + 0.3);
    });
  } catch {}
}

// ----------------------------------------------------------------- TTS
let voices = [];
function loadVoices() { voices = speechSynthesis.getVoices(); renderVoiceSelect(); }
speechSynthesis.onvoiceschanged = loadVoices; loadVoices();

function utter(text) {
  const u = new SpeechSynthesisUtterance(text);
  const p = persona(); const s = S.settings;
  const v = voices.find((x) => x.name === s.tts_voice) || voices.find((x) => /en[-_](GB|IN|US)/i.test(x.lang) && /male|david|daniel|guy|ryan|george/i.test(x.name)) || voices.find((x) => /^en/i.test(x.lang));
  if (v) u.voice = v;
  u.rate = (s.tts_rate || 1) * (p.tts_rate || 1);
  u.pitch = (s.tts_pitch || 1) * (p.tts_pitch || 1);
  u.onstart = () => { setMood("speaking"); recognizer.pause(); };
  u.onend = u.onerror = () => { if (!speechSynthesis.pending && !speechSynthesis.speaking) { setMood(busy ? "thinking" : null); recognizer.resume(); } };
  return u;
}
function speak(text, force = false) {
  if (!text || (!force && !S.settings.tts_enabled)) return;
  speechSynthesis.speak(utter(text));
}
// Speaks a streaming reply sentence-by-sentence so JIM starts talking immediately.
const speaker = {
  said: 0,
  reset() { this.said = 0; },
  feed(full) {
    const clean = speakable(full);
    const rest = clean.slice(this.said);
    const m = rest.match(/^[\s\S]*?[.!?](\s|$)/);
    if (m && m[0].trim().length > 2 && !/```[^`]*$/.test(full)) { speak(m[0].trim()); this.said += m[0].length; }
  },
  finish(full) { const rest = speakable(full).slice(this.said).trim(); if (rest) speak(rest); this.said = 0; },
};
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { speechSynthesis.cancel(); setMood(null); recognizer.resume(); } });

// ------------------------------------------------------------- speech in
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const recognizer = {
  rec: null, mode: null /* 'once' | 'wake' */, paused: false, awakeUntil: 0, recording: null,

  wakeRx() { const w = (S.settings.wake_word || "jim").replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); return new RegExp(`^\\s*(?:hey|hi|ok|okay)?\\s*,?\\s*(?:${w}|gym|jimmy|jym)\\b[\\s,.!:]*`, "i"); },

  start(mode) {
    if (S.settings.stt_engine === "whisper" && mode === "once") return this.whisperToggle();
    if (!SR) { toast("Voice needs Chrome or Edge (or switch to Whisper in Settings → Voice)."); return; }
    this.stop(); this.mode = mode;
    const r = new SR(); this.rec = r;
    r.lang = navigator.language || "en-US"; r.interimResults = true; r.continuous = mode === "wake"; r.maxAlternatives = 1;
    r.onstart = () => { if (mode === "once") { setMood("listening"); setStatus("Listening…"); } };
    r.onresult = (e) => {
      let interim = "", final = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript; e.results[i].isFinal ? (final += t) : (interim += t);
      }
      $("#interim").textContent = interim;
      if (final) this.onFinal(final.trim());
    };
    r.onerror = (e) => { if (e.error === "not-allowed") { toast("Microphone permission denied."); $("#wakeToggle").checked = false; this.mode = null; } };
    r.onend = () => {
      $("#interim").textContent = "";
      if (this.mode === "once") { this.mode = null; if (document.body.classList.contains("listening")) setMood(null); setStatus("Ready"); restoreWake(); }
      else if (this.mode === "wake" && !this.paused) setTimeout(() => { try { r.start(); } catch {} }, 250);
    };
    try { r.start(); } catch {}
  },
  onFinal(text) {
    if (this.mode === "once") { send(text, true); return; }
    const rx = this.wakeRx(); const hasWake = rx.test(text);
    if (!hasWake && Date.now() > this.awakeUntil) return;
    const cmd = text.replace(rx, "").trim();
    if (!cmd) { this.wake(8000); speak("Yes?", true); return; }
    document.body.classList.remove("awake"); this.awakeUntil = 0;
    send(cmd, true);
    this.wake(10000);                       // follow-ups without the wake word for 10 s
  },
  wake(ms) { this.awakeUntil = Date.now() + ms; document.body.classList.add("awake"); setTimeout(() => { if (Date.now() >= this.awakeUntil) document.body.classList.remove("awake"); }, ms + 50); },
  stop() { this.mode = null; if (this.rec) { try { this.rec.abort(); } catch {} this.rec = null; } },
  pause() { this.paused = true; if (this.mode === "wake" && this.rec) { try { this.rec.abort(); } catch {} } },
  resume() { if (!this.paused) return; this.paused = false; if (this.mode === "wake" && this.rec) { try { this.rec.start(); } catch {} } },

  // --- offline Whisper: record → send to /api/transcribe (auto-stops on silence)
  async whisperToggle() {
    if (this.recording) { this.recording.stop(); return; }
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch { toast("Microphone permission denied."); return; }
    const rec = new MediaRecorder(stream); const chunks = []; this.recording = rec;
    const ctx = new AudioContext(); const an = ctx.createAnalyser(); ctx.createMediaStreamSource(stream).connect(an);
    const data = new Uint8Array(an.fftSize); let heard = false, quietSince = Date.now(); const started = Date.now();
    const loop = setInterval(() => {
      an.getByteTimeDomainData(data); const lvl = Math.max(...data.map((v) => Math.abs(v - 128)));
      if (lvl > 12) { heard = true; quietSince = Date.now(); }
      if ((heard && Date.now() - quietSince > 1400) || Date.now() - started > 20000) rec.stop();
    }, 100);
    rec.ondataavailable = (e) => chunks.push(e.data);
    rec.onstop = async () => {
      clearInterval(loop); stream.getTracks().forEach((t) => t.stop()); ctx.close(); this.recording = null;
      setMood("thinking"); setStatus("Transcribing…");
      try {
        const r = await api("/api/transcribe", { method: "POST", body: new Blob(chunks, { type: rec.mimeType }), headers: { "Content-Type": "application/octet-stream" } });
        setMood(null); setStatus("Ready");
        if (r.text) send(r.text, true); else toast("Didn't catch that.");
      } catch (e) { setMood(null); setStatus("Ready"); toast(String(e.message).slice(0, 160)); }
    };
    rec.start(); setMood("listening"); setStatus("Listening (Whisper)…");
  },
};
function restoreWake() { if ($("#wakeToggle").checked) setTimeout(() => recognizer.start("wake"), 300); }
function talk() {
  speechSynthesis.cancel();
  if (recognizer.mode === "once" || recognizer.recording) { recognizer.stop(); recognizer.recording?.stop(); setMood(null); return; }
  recognizer.start("once");
}
$("#micBtn").onclick = talk; $("#miniOrb").onclick = talk; $("#bigOrb").onclick = talk;
document.addEventListener("keydown", (e) => { if (e.ctrlKey && e.code === "Space") { e.preventDefault(); talk(); } });
$("#wakeToggle").onchange = async (e) => {
  await saveSettings({ wake_word_enabled: e.target.checked });
  if (e.target.checked) {
    if (S.settings.stt_engine === "whisper") toast("Wake word uses browser recognition. For offline hands-free, run voice_daemon.py.");
    recognizer.start("wake"); toast(`Listening for “${cap(S.settings.wake_word || "jim")}”`);
  } else { recognizer.stop(); document.body.classList.remove("awake"); }
};

// --------------------------------------------------------------- composer
const input = $("#input");
function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 180) + "px"; }
input.addEventListener("input", autosize);
input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input.value); } });
$("#sendBtn").onclick = () => send(input.value);
$$("#examples .chip").forEach((c) => (c.onclick = () => send(c.textContent)));

// ------------------------------------------------------------ conversations
async function loadConvs() {
  const list = await api("/api/conversations");
  $("#convList").innerHTML = list.map((c) => `<div class="conv ${c.id === convId ? "active" : ""}" data-id="${c.id}"><span>${esc(c.title)}</span><button class="del" title="Delete">🗑</button></div>`).join("")
    || `<div class="muted small" style="padding:8px">No chats yet</div>`;
}
$("#convList").onclick = async (e) => {
  const row = e.target.closest(".conv"); if (!row) return;
  if (e.target.classList.contains("del")) {
    await api(`/api/conversations/${row.dataset.id}`, { method: "DELETE" });
    if (row.dataset.id === convId) newChat(); loadConvs(); return;
  }
  convId = row.dataset.id; msgs.innerHTML = ""; $("#welcome").classList.add("hidden");
  for (const m of await api(`/api/conversations/${convId}`)) addMsg(m.role === "user" ? "user" : "bot", m.role === "user" ? esc(m.content) : md(m.content));
  loadConvs(); $("#sidebar").classList.remove("open");
};
function newChat() { convId = null; msgs.innerHTML = ""; $("#welcome").classList.remove("hidden"); loadConvs(); $("#sidebar").classList.remove("open"); }
$("#newChat").onclick = newChat;
$("#menuBtn").onclick = () => $("#sidebar").classList.toggle("open");

// ================================================================ SETTINGS
const PRESETS = [
  { name: "Custom", url: "", model: "" },
  { name: "Ollama (local)", url: "http://localhost:11434/v1", model: "qwen2.5:7b", link: "https://ollama.com/library", no_key: true },
  { name: "LM Studio (local)", url: "http://localhost:1234/v1", model: "local-model", link: "https://lmstudio.ai", no_key: true },
  { name: "Groq", url: "https://api.groq.com/openai/v1", model: "llama-3.3-70b-versatile", link: "https://console.groq.com/keys" },
  { name: "Google Gemini", url: "https://generativelanguage.googleapis.com/v1beta/openai", model: "gemini-2.5-flash", link: "https://aistudio.google.com/apikey" },
  { name: "Cerebras", url: "https://api.cerebras.ai/v1", model: "gpt-oss-120b", link: "https://cloud.cerebras.ai" },
  { name: "OpenRouter", url: "https://openrouter.ai/api/v1", model: "deepseek/deepseek-chat-v3-0324:free", link: "https://openrouter.ai/models?max_price=0" },
  { name: "Mistral", url: "https://api.mistral.ai/v1", model: "mistral-small-latest", link: "https://console.mistral.ai/api-keys" },
  { name: "GitHub Models", url: "https://models.github.ai/inference", model: "openai/gpt-4.1-mini", link: "https://github.com/marketplace/models" },
  { name: "Hugging Face router", url: "https://router.huggingface.co/v1", model: "meta-llama/Llama-3.3-70B-Instruct", link: "https://huggingface.co/settings/tokens" },
  { name: "NVIDIA NIM", url: "https://integrate.api.nvidia.com/v1", model: "meta/llama-3.3-70b-instruct", link: "https://build.nvidia.com" },
  { name: "SambaNova", url: "https://api.sambanova.ai/v1", model: "Meta-Llama-3.3-70B-Instruct", link: "https://cloud.sambanova.ai/apis" },
  { name: "Together AI", url: "https://api.together.xyz/v1", model: "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free", link: "https://api.together.ai/settings/api-keys" },
  { name: "DeepSeek", url: "https://api.deepseek.com/v1", model: "deepseek-chat", link: "https://platform.deepseek.com/api_keys" },
  { name: "OpenAI", url: "https://api.openai.com/v1", model: "gpt-4o-mini", link: "https://platform.openai.com/api-keys" },
];

function openSettings(tab = "models") {
  $("#settings").classList.remove("hidden"); switchTab(tab); fillSettings();
}
function switchTab(tab) {
  $$("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $$(".tab-pane").forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== tab));
  if (tab === "memory") loadFacts();
}
$$("[data-open-settings]").forEach((b) => (b.onclick = () => openSettings(b.dataset.openSettings)));
$("#tabs").onclick = (e) => e.target.dataset.tab && switchTab(e.target.dataset.tab);
$("#closeSettings").onclick = () => $("#settings").classList.add("hidden");
$("#settings").onclick = (e) => { if (e.target.id === "settings") $("#settings").classList.add("hidden"); };

function fillSettings() {
  const s = S.settings;
  renderProviders();
  $("#councilSize").value = s.council_size;
  $("#synthSel").innerHTML = `<option value="">First available</option>` + usable().map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
  $("#synthSel").value = s.synthesizer || "";
  $("#presetSel").innerHTML = PRESETS.map((p, i) => `<option value="${i}">${esc(p.name)}</option>`).join("");
  renderPersonaEditor(s.personality);
  // voice
  $("#sttSel").value = s.stt_engine; $("#whisperSel").value = s.whisper_model; $("#wakeWord").value = s.wake_word;
  setRange("vRate", s.tts_rate); setRange("vPitch", s.tts_pitch); renderVoiceSelect();
  // system
  $("#aName").value = s.assistant_name; $("#uName").value = s.user_name; setRange("temp", s.temperature);
  $("#maxTok").value = s.max_tokens; $("#histTurns").value = s.history_turns;
  $("#allowCtl").checked = s.allow_system_control; $("#confirmRisky").checked = s.confirm_risky; $("#allowShell").checked = s.allow_shell;
  $("#toolList").innerHTML = S.tools.map((t) => `<div class="${t.risky ? "risky" : ""}"><b>${t.name}</b><br>${esc(t.description)}</div>`).join("");
  $("#platformInfo").textContent = `Running on ${S.platform}${S.dry_run ? " · DRY RUN (actions are simulated)" : ""}`;
}
function setRange(id, v) { $("#" + id).value = v; $("#" + id + "V").textContent = Number(v).toFixed(2); }
["vRate", "vPitch", "temp", "pRate", "pPitch"].forEach((id) => $("#" + id).addEventListener("input", (e) => ($("#" + id + "V").textContent = Number(e.target.value).toFixed(2))));

$("#councilSize").onchange = (e) => saveSettings({ council_size: +e.target.value });
$("#synthSel").onchange = (e) => saveSettings({ synthesizer: e.target.value });

// ---- providers
function renderProviders() {
  $("#providerList").innerHTML = S.providers.map((p) => {
    const ready = p.has_key || p.no_key;
    return `<div class="card ${p.enabled ? "" : "off"}" data-id="${p.id}">
      <div class="card-head"><span class="dot ${ready ? "" : "nokey"}" title="${ready ? "" : "needs API key"}"></span><b>${esc(p.name)}</b>
        <label class="switch" title="Enabled"><input type="checkbox" data-f="enabled" ${p.enabled ? "checked" : ""}><span class="slider"></span></label></div>
      <label>Model <input data-f="model" value="${esc(p.model)}" list="models-${p.id}"><datalist id="models-${p.id}"></datalist></label>
      ${p.no_key ? "" : `<label>API key <input data-f="api_key" type="password" value="${esc(p.api_key)}" placeholder="paste your key"></label>`}
      <details><summary class="note">Advanced</summary>
        <label>Base URL <input data-f="base_url" value="${esc(p.base_url)}"></label>
        <label>Priority (lower = tried first) <input data-f="priority" type="number" class="prio" value="${p.priority ?? 9}"></label>
      </details>
      ${p.notes ? `<div class="note">${esc(p.notes)}</div>` : ""}
      <div class="btns"><button class="btn small primary" data-act="save">Save</button><button class="btn small" data-act="test">Test</button>
        <button class="btn small" data-act="models">Fetch models</button><button class="btn small danger" data-act="del">✕</button>
        ${p.signup_url ? `<a class="link" href="${esc(p.signup_url)}" target="_blank">get key ↗</a>` : ""}</div>
      <div class="result"></div></div>`;
  }).join("");
}
function cardData(card) {
  const d = { id: card.dataset.id };
  $$("[data-f]", card).forEach((i) => (d[i.dataset.f] = i.type === "checkbox" ? i.checked : i.type === "number" ? +i.value : i.value.trim()));
  return d;
}
$("#providerList").addEventListener("click", async (e) => {
  const act = e.target.dataset.act; if (!act) return;
  const card = e.target.closest(".card"); const id = card.dataset.id; const res = $(".result", card); const dot = $(".dot", card);
  res.className = "result"; res.textContent = "…";
  try {
    if (act === "save" || act === "test") { await api("/api/providers", { method: "POST", body: cardData(card) }); }
    if (act === "save") { res.textContent = "Saved ✓"; res.classList.add("ok"); }
    if (act === "test") {
      const r = await api(`/api/providers/${id}/test`, { method: "POST" });
      res.textContent = r.ok ? `Online ✓ “${r.reply}”` : r.error; res.classList.add(r.ok ? "ok" : "bad"); dot.className = "dot " + (r.ok ? "ok" : "bad");
    }
    if (act === "models") {
      await api("/api/providers", { method: "POST", body: cardData(card) });
      const r = await api(`/api/providers/${id}/models`);
      if (r.ok) { $(`#models-${id}`).innerHTML = r.models.map((m) => `<option value="${esc(m)}">`).join(""); res.textContent = `${r.models.length} models found — click the Model box to pick one.`; res.classList.add("ok"); }
      else { res.textContent = r.error; res.classList.add("bad"); }
    }
    if (act === "del") { if (!confirm("Remove this model?")) { res.textContent = ""; return; } await api(`/api/providers/${id}`, { method: "DELETE" }); }
    await refreshProviders(act === "del");
  } catch (err) { res.textContent = err.message; res.classList.add("bad"); }
});
$("#providerList").addEventListener("change", async (e) => {
  if (e.target.dataset.f === "enabled") { const card = e.target.closest(".card"); await api("/api/providers", { method: "POST", body: cardData(card) }); card.classList.toggle("off", !e.target.checked); refreshProviders(false); }
});
async function refreshProviders(rerender = true) {
  S.providers = await api("/api/providers"); renderSingleSelect(); renderModelCount(); if (rerender) renderProviders();
}
$("#presetSel").onchange = (e) => {
  const p = PRESETS[+e.target.value];
  $("#newName").value = p.name === "Custom" ? "" : p.name; $("#newUrl").value = p.url; $("#newModel").value = p.model;
  $("#presetLink").textContent = p.link ? "Get a key / browse models ↗" : ""; $("#presetLink").href = p.link || "#";
  $("#newKey").placeholder = p.no_key ? "not needed (local)" : "paste key";
};
$("#addProvider").onclick = async () => {
  const preset = PRESETS[+$("#presetSel").value];
  const data = { name: $("#newName").value.trim(), base_url: $("#newUrl").value.trim(), model: $("#newModel").value.trim(), api_key: $("#newKey").value.trim(), no_key: !!preset.no_key || !$("#newKey").value.trim(), enabled: true, signup_url: preset.link || "" };
  if (!data.name || !data.base_url || !data.model) { toast("Name, base URL and model are required."); return; }
  await api("/api/providers", { method: "POST", body: data });
  ["newName", "newUrl", "newModel", "newKey"].forEach((i) => ($("#" + i).value = ""));
  await refreshProviders(); toast(`${data.name} added — hit Test on its card.`);
};

// ---- personalities
let editingPersona = null;
function renderPersonaEditor(id) {
  $("#personaList").innerHTML = S.personalities.map((p) => `<button data-id="${p.id}" class="${p.id === id ? "active" : ""}">${p.emoji || ""} ${esc(p.name)}</button>`).join("");
  const p = S.personalities.find((x) => x.id === id) || { id: "", name: "", emoji: "✨", prompt: "", tts_rate: 1, tts_pitch: 1 };
  editingPersona = p.id;
  $("#pName").value = p.name; $("#pEmoji").value = p.emoji || ""; $("#pPrompt").value = p.prompt; setRange("pRate", p.tts_rate || 1); setRange("pPitch", p.tts_pitch || 1);
}
$("#personaList").onclick = (e) => e.target.dataset.id && renderPersonaEditor(e.target.dataset.id);
$("#pNew").onclick = () => { renderPersonaEditor(null); $("#pName").focus(); };
$("#pSave").onclick = async () => {
  const data = { id: editingPersona || undefined, name: $("#pName").value.trim() || "Custom", emoji: $("#pEmoji").value.trim(), prompt: $("#pPrompt").value.trim(), tts_rate: +$("#pRate").value, tts_pitch: +$("#pPitch").value };
  const saved = await api("/api/personalities", { method: "POST", body: data });
  await loadState(); renderPersonaEditor(saved.id); toast("Personality saved");
};
$("#pDelete").onclick = async () => {
  if (!editingPersona || !confirm("Delete this personality?")) return;
  await api(`/api/personalities/${editingPersona}`, { method: "DELETE" });
  await loadState(); renderPersonaEditor(S.settings.personality);
};
$("#pTest").onclick = () => {
  const u = utter(`Hello, I'm ${S.settings.assistant_name || "JIM"}. This is how I sound in ${$("#pName").value || "this"} mode.`);
  u.rate = (S.settings.tts_rate || 1) * +$("#pRate").value; u.pitch = (S.settings.tts_pitch || 1) * +$("#pPitch").value;
  speechSynthesis.cancel(); speechSynthesis.speak(u);
};

// ---- voice
function renderVoiceSelect() {
  const sel = $("#voiceSel"); if (!sel) return;
  sel.innerHTML = `<option value="">Auto</option>` + voices.map((v) => `<option value="${esc(v.name)}">${esc(v.name)} (${v.lang})</option>`).join("");
  sel.value = S.settings.tts_voice || "";
}
$("#saveVoice").onclick = async () => {
  await saveSettings({ stt_engine: $("#sttSel").value, whisper_model: $("#whisperSel").value, wake_word: $("#wakeWord").value.trim().toLowerCase() || "jim", tts_voice: $("#voiceSel").value, tts_rate: +$("#vRate").value, tts_pitch: +$("#vPitch").value });
  $("#wakeLabel").textContent = cap(S.settings.wake_word); toast("Voice settings saved");
};
$("#testVoice").onclick = () => {
  const old = { ...S.settings }; Object.assign(S.settings, { tts_voice: $("#voiceSel").value, tts_rate: +$("#vRate").value, tts_pitch: +$("#vPitch").value });
  speechSynthesis.cancel(); speak(`All systems online. How can I help?`, true); Object.assign(S.settings, old);
};

// ---- system
$("#saveSystem").onclick = async () => {
  await saveSettings({ assistant_name: $("#aName").value.trim() || "JIM", user_name: $("#uName").value.trim(), temperature: +$("#temp").value, max_tokens: +$("#maxTok").value, history_turns: +$("#histTurns").value, allow_system_control: $("#allowCtl").checked, confirm_risky: $("#confirmRisky").checked, allow_shell: $("#allowShell").checked });
  await loadState(); toast("Saved");
};

// ---- memory
async function loadFacts() {
  const f = await api("/api/facts");
  $("#factList").innerHTML = f.map((x) => `<li><span>${esc(x.fact)}</span><button class="icon-btn" data-id="${x.id}">🗑</button></li>`).join("") || `<li class="muted">Nothing remembered yet.</li>`;
}
$("#factList").onclick = async (e) => { if (e.target.dataset.id) { await api(`/api/facts/${e.target.dataset.id}`, { method: "DELETE" }); loadFacts(); } };
$("#addFact").onclick = async () => { const v = $("#factInput").value.trim(); if (!v) return; await api("/api/facts", { method: "POST", body: { fact: v } }); $("#factInput").value = ""; loadFacts(); };

// ------------------------------------------------------------------ boot
(async () => {
  try { await loadState(); } catch (e) { setStatus("Server offline"); return; }
  loadConvs();
  if (!usable().length) setTimeout(() => { openSettings("models"); toast("Add at least one model to wake JIM up — Groq and Gemini keys are free.", 6000); }, 600);
  if (S.settings.wake_word_enabled) { $("#wakeToggle").checked = true; recognizer.start("wake"); }
  input.focus();
})();
