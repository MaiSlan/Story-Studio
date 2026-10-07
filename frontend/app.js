/* Story Studio front end: plain JavaScript, no build step. */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  config: null,
  track: "pinyin",
  length: "medium",
  story: null,        // story currently open
  validation: null,
  dirty: false,
  jobTimer: null,
  jobId: null,
  library: [],
};

/* ------------------------------------------------------------------ talking to the backend */
// window.STORY_STUDIO_API comes from config.js: "" = same address as this page, else the backend's URL.
const API_BASE = String(window.STORY_STUDIO_API || "").replace(/\/+$/, "");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function getToken() { try { return localStorage.getItem("ss.token") || ""; } catch (_) { return ""; } }
function setToken(t) { try { localStorage.setItem("ss.token", t); } catch (_) {} }

// HTTP Basic, UTF-8 encoded, so passwords with accents or Chinese characters work too (header values must be Latin-1).
function basicAuth(password) {
  let bin = "";
  new TextEncoder().encode("story:" + password).forEach((b) => { bin += String.fromCharCode(b); });
  return "Basic " + btoa(bin);
}

let pwPromise = null;
function askPassword(wasWrong) {
  if (pwPromise) return pwPromise;
  const dlg = $("#pw-dialog"), input = $("#pw-input");
  $("#pw-error").hidden = !wasWrong;
  input.value = "";
  pwPromise = new Promise((resolve) => {
    dlg.addEventListener("cancel", (e) => e.preventDefault(), { once: true });
    $("#pw-form").addEventListener("submit", () => {
      setToken(input.value.trim());
      pwPromise = null;
      resolve();
    }, { once: true });
  });
  if (!dlg.open) dlg.showModal();
  input.focus();
  return pwPromise;
}

async function request(path, init = {}) {
  for (;;) {
    const headers = { ...(init.headers || {}) };
    const token = getToken();
    if (token) headers.Authorization = basicAuth(token);
    let res;
    try {
      res = await fetch(API_BASE + path, { ...init, headers });
    } catch (_) {
      throw new Error("Cannot reach the server" + (API_BASE ? " at " + API_BASE : "") + ". If it was asleep it needs up to a minute to wake: try again shortly.");
    }
    if (res.status === 401) { await askPassword(!!token); continue; }
    return res;
  }
}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  const res = await request(path, init);
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = j.detail || JSON.stringify(j); } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json();
}

function banner(text, bad = false, ms = 0) {
  const b = $("#banner");
  b.textContent = text;
  b.className = "banner" + (bad ? " bad" : "");
  b.hidden = false;
  if (ms) setTimeout(() => { if (b.textContent === text) b.hidden = true; }, ms);
}

// Free hosts put idle servers to sleep. Poke /api/health until it answers so the first real request does not fail.
async function wakeServer() {
  if (!API_BASE) return;
  const note = setTimeout(() => banner("Waking up the server. The first visit after a pause can take up to a minute."), 2000);
  for (let i = 0; i < 40; i++) {
    try { const r = await fetch(API_BASE + "/api/health", { cache: "no-store" }); if (r.ok) break; } catch (_) {}
    await sleep(3000);
  }
  clearTimeout(note);
  $("#banner").hidden = true;
}

// PDFs and JSON come through fetch (so the password can be sent), then open or save as a local file.
async function fetchFile(path) {
  const res = await request(path);
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    throw new Error(String(msg));
  }
  const m = /filename="?([^";]+)"?/.exec(res.headers.get("Content-Disposition") || "");
  return { blob: await res.blob(), name: m ? m[1] : "story" };
}

async function saveFile(path) {
  try {
    const { blob, name } = await fetchFile(path);
    const url = URL.createObjectURL(blob);
    const a = el("a", { href: url, download: name });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (e) { banner("Could not download: " + e.message, true, 8000); }
}

async function previewPdf(path) {
  const win = window.open("", "_blank");   // opened inside the click so pop-up blockers allow it
  if (win) win.document.write("<p style='font:16px sans-serif;padding:24px'>Preparing the PDF...</p>");
  try {
    const { blob } = await fetchFile(path);
    const url = URL.createObjectURL(blob);
    if (win) win.location.href = url; else await saveFile(path + (path.includes("?") ? "&" : "?") + "download=true");
    setTimeout(() => URL.revokeObjectURL(url), 10 * 60000);
  } catch (e) {
    if (win) win.close();
    banner("Could not make the PDF: " + e.message, true, 8000);
  }
}

function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v === true) node.setAttribute(k, "");
    else if (v !== false && v != null) node.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) node.append(kid.nodeType ? kid : document.createTextNode(kid));
  return node;
}

function remember(key, value) { try { localStorage.setItem("ss." + key, value); } catch (_) {} }
function recall(key, fallback) { try { return localStorage.getItem("ss." + key) ?? fallback; } catch (_) { return fallback; } }

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/* ------------------------------------------------------------------ navigation */
function showView(name) {
  for (const v of $$(".view")) v.hidden = v.id !== "view-" + name;
  for (const t of $$(".tabs button")) t.setAttribute("aria-selected", String(t.dataset.view === name || (name === "story" && t.dataset.view === "library")));
  if (name === "library") loadLibrary();
  if (name === "connections") renderProviders();
  window.scrollTo(0, 0);
}
$$(".tabs button").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));

/* ------------------------------------------------------------------ config + form */
async function init() {
  await wakeServer();
  state.config = await api("/api/config");
  const c = state.config;

  // length segments
  const seg = $("#length-seg");
  seg.replaceChildren(...c.lengths.map((l) => {
    const short = l.id === "custom" ? "Custom" : l.id[0].toUpperCase() + l.id.slice(1) + " · " + l.lines;
    return el("button", { type: "button", role: "radio", "data-length": l.id, "aria-checked": "false", title: l.label, text: short });
  }));
  seg.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setLength(b.dataset.length); });

  // selects
  $("#voice").replaceChildren(...c.voices.map((v) => el("option", { value: v.id, text: v.label })));
  $("#source").replaceChildren(...c.source_modes.map((v) => el("option", { value: v.id, text: v.label })));
  $("#provider").replaceChildren(...c.providers.map((p) => el("option", { value: p.id, text: p.label + (p.configured ? "" : "  (no key yet)") })));

  // restore previous choices
  $("#provider").value = recall("provider", c.default_provider);
  if (!c.providers.find((p) => p.id === $("#provider").value)) $("#provider").value = c.default_provider;
  $("#level").value = recall("level", "2");
  $("#voice").value = recall("voice", "auto");
  $("#source").value = recall("source", "auto");
  setTrack(recall("track", "pinyin"), true);
  setLength(recall("length", "medium"));
  updateProviderUI();
  updateLevel();

  $("#track-seg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setTrack(b.dataset.track); });
  $("#level").addEventListener("input", () => { updateLevel(); remember("level", $("#level").value); });
  $("#provider").addEventListener("change", () => { remember("provider", $("#provider").value); updateProviderUI(); });
  $("#model").addEventListener("change", () => remember("model." + $("#provider").value, $("#model").value));
  $("#voice").addEventListener("change", () => remember("voice", $("#voice").value));
  $("#source").addEventListener("change", () => remember("source", $("#source").value));
  $("#brief").addEventListener("submit", onGenerate);
  $("#btn-ideas").addEventListener("click", onIdeas);
  $("#btn-ideas-more").addEventListener("click", onIdeas);
  $("#btn-cancel").addEventListener("click", onCancel);
  $("#lib-filter").addEventListener("input", renderLibrary);

  loadLibraryCount();
}

function setTrack(track, silent) {
  state.track = track;
  document.body.dataset.track = track;
  for (const b of $$("#track-seg button")) b.setAttribute("aria-checked", String(b.dataset.track === track));
  $("#track-hint").textContent = track === "pinyin"
    ? "Pinyin (bold, read aloud), hanzi (grey) and English (small italic)."
    : "French (bold, read aloud), hanzi (grey) and English (small italic).";
  if (!silent) remember("track", track);
  else remember("track", track);
  updateLevel();
}

function setLength(len) {
  state.length = len;
  for (const b of $$("#length-seg button")) b.setAttribute("aria-checked", String(b.dataset.length === len));
  $("#custom-wrap").hidden = len !== "custom";
  remember("length", len);
}

function updateLevel() {
  const lvl = $("#level").value;
  $("#level-out").textContent = lvl;
  const text = state.config.levels[state.track][lvl] || "";
  $("#level-hint").textContent = text;
}

function updateProviderUI() {
  const p = state.config.providers.find((x) => x.id === $("#provider").value);
  if (!p) return;
  $("#model").value = recall("model." + p.id, "");
  $("#model").placeholder = p.model;
  $("#model-list").replaceChildren(...p.suggestions.map((m) => el("option", { value: m })));
}

function currentProvider() {
  const id = $("#provider").value;
  return { provider: id, model: $("#model").value.trim() || null };
}

/* ------------------------------------------------------------------ ideas */
async function onIdeas() {
  const btns = [$("#btn-ideas"), $("#btn-ideas-more")];
  btns.forEach((b) => { b.disabled = true; b.textContent = "Thinking..."; });
  hideSide();
  try {
    const { ideas } = await api("/api/ideas", { method: "POST", body: { track: state.track, theme: $("#topic").value, count: 8, ...currentProvider() } });
    const list = $("#ideas-list");
    list.replaceChildren(...ideas.map((idea) => el("li", {},
      el("button", { type: "button", onclick: () => useIdea(idea) },
        el("strong", { text: idea.title }),
        el("span", { class: "pitch", text: idea.pitch }),
        el("span", { class: "tags" },
          idea.source_mode !== "auto" ? el("span", { class: "tag", text: labelOf("source_modes", idea.source_mode) }) : null,
          idea.voice !== "auto" ? el("span", { class: "tag", text: labelOf("voices", idea.voice) }) : null)))));
    $("#side-ideas").hidden = false;
  } catch (err) {
    showSideError(err.message);
  } finally {
    $("#btn-ideas").textContent = "Suggest ideas";
    $("#btn-ideas-more").textContent = "Suggest more";
    btns.forEach((b) => { b.disabled = false; });
  }
}

function labelOf(kind, id) {
  const item = state.config[kind].find((x) => x.id === id);
  return item ? item.label.split(":")[0].split("(")[0].trim() : id;
}

function useIdea(idea) {
  $("#topic").value = idea.title + ". " + idea.pitch;
  if ([...$("#source").options].some((o) => o.value === idea.source_mode)) $("#source").value = idea.source_mode;
  if ([...$("#voice").options].some((o) => o.value === idea.voice)) $("#voice").value = idea.voice;
  $("#topic").focus();
}

/* ------------------------------------------------------------------ generate */
function hideSide() { for (const id of ["side-empty", "side-ideas", "side-progress", "side-error"]) $("#" + id).hidden = true; }
function showSideError(msg) { hideSide(); $("#side-error-msg").textContent = msg; $("#side-error").hidden = false; }

async function onGenerate(ev) {
  ev.preventDefault();
  const err = $("#brief-error");
  err.hidden = true;
  const topic = $("#topic").value.trim();
  if (topic.length < 3) { err.textContent = "Add a topic first (a few words is enough)."; err.hidden = false; $("#topic").focus(); return; }
  const body = {
    track: state.track,
    topic,
    length: state.length,
    custom_lines: state.length === "custom" ? Number($("#custom-lines").value) : null,
    level: Number($("#level").value),
    voice: $("#voice").value,
    source_mode: $("#source").value,
    notes: $("#notes").value,
    ...currentProvider(),
  };
  $("#btn-generate").disabled = true;
  try {
    const { job_id } = await api("/api/jobs", { method: "POST", body });
    state.jobId = job_id;
    hideSide();
    $("#side-progress").hidden = false;
    $("#prog-title").textContent = "Writing your story";
    $("#prog-msg").textContent = "Starting...";
    $("#prog-lines").textContent = "";
    $("#prog-fill").style.width = "4%";
    $("#btn-cancel").disabled = false;
    pollJob();
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
    $("#btn-generate").disabled = false;
  }
}

let pollFailures = 0;
function pollJob(delay = 900) {
  clearTimeout(state.jobTimer);
  state.jobTimer = setTimeout(async () => {
    try {
      const j = await api("/api/jobs/" + state.jobId);
      pollFailures = 0;
      const pct = j.total_lines ? Math.min(100, Math.round((j.done_lines / j.total_lines) * 100)) : 0;
      $("#prog-fill").style.width = Math.max(pct, j.status === "running" ? 4 : 0) + "%";
      $("#prog-msg").textContent = j.message;
      $("#prog-lines").textContent = j.total_lines ? `${j.done_lines} of about ${j.total_lines} lines` : "";
      if (j.status === "done") {
        $("#btn-generate").disabled = false;
        loadLibraryCount();
        await openStory(j.story_id);
        hideSide(); $("#side-empty").hidden = false;
        return;
      }
      if (j.status === "error") { $("#btn-generate").disabled = false; showSideError(j.error || "Unknown error."); return; }
      if (j.status === "cancelled") { $("#btn-generate").disabled = false; hideSide(); $("#side-empty").hidden = false; return; }
      pollJob();
    } catch (e) {
      // A short network hiccup (or a host that is restarting) should not throw the whole job away.
      if (/Cannot reach/.test(e.message) && ++pollFailures <= 8) { $("#prog-msg").textContent = "Reconnecting to the server..."; pollJob(4000); return; }
      pollFailures = 0;
      $("#btn-generate").disabled = false;
      showSideError(/Unknown job/.test(e.message) ? "The server restarted while writing and lost this job. Nothing was saved; please start it again." : e.message);
    }
  }, delay);
}

async function onCancel() {
  if (!state.jobId) return;
  $("#btn-cancel").disabled = true;
  try { await api(`/api/jobs/${state.jobId}/cancel`, { method: "POST" }); } catch (_) {}
  $("#btn-cancel").disabled = false;
}

/* ------------------------------------------------------------------ library */
async function loadLibraryCount() {
  try { const { stories } = await api("/api/stories"); state.library = stories; $("#lib-count").textContent = stories.length ? String(stories.length) : ""; } catch (_) {}
}
async function loadLibrary() { await loadLibraryCount(); renderLibrary(); }

function renderLibrary() {
  const q = $("#lib-filter").value.trim().toLowerCase();
  const rows = state.library.filter((s) => !q || [s.title.english, s.title.primary, s.title.hanzi, s.topic].join(" ").toLowerCase().includes(q));
  $("#lib-empty").hidden = state.library.length > 0;
  $("#lib-list").replaceChildren(...rows.map((s) => el("li", { "data-track": s.track },
    el("button", { onclick: () => openStory(s.id) },
      el("span", { class: "stripe" }),
      el("span", {},
        el("div", { class: "t1", text: s.title.english || s.title.primary }),
        el("div", { class: "t2" }, s.title.primary, s.title.hanzi ? " · " : "", el("span", { class: "zh", text: s.title.hanzi }))),
      el("span", { class: "meta", text: `${s.track === "pinyin" ? "Pinyin" : "Français"} · level ${s.level} · ${s.lines} lines · ${fmtDate(s.created)}` })))));
}

/* ------------------------------------------------------------------ story view */
async function openStory(id) {
  const data = await api("/api/stories/" + id);
  state.story = data.story;
  state.validation = data.validation;
  state.dirty = false;
  document.body.dataset.track = data.story.track;
  renderStory();
  showView("story");
}

function editable(cls, text, onInput) {
  const node = el("div", { class: "f " + cls, contenteditable: "true", spellcheck: "false" });
  node.textContent = text;
  node.addEventListener("input", onInput);
  node.addEventListener("paste", (e) => {
    e.preventDefault();
    const t = (e.clipboardData || window.clipboardData).getData("text/plain").replace(/\s*\n\s*/g, " ");
    document.execCommand("insertText", false, t);
  });
  node.addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });
  return node;
}

function renderStory() {
  const s = state.story;
  const markDirty = () => { state.dirty = true; $("#btn-save").disabled = false; $("#save-state").textContent = "Unsaved changes"; };

  const title = $("#story-title");
  title.replaceChildren(
    editable("p", s.title.primary, markDirty),
    editable("z", s.title.hanzi, markDirty),
    editable("e", s.title.english, markDirty));
  title.firstChild.className = "f p"; title.children[1].className = "f z"; title.children[2].className = "f e";

  const trackName = s.track === "pinyin" ? "Pinyin reading" : "Lecture en français";
  $("#story-meta").textContent = `${trackName} · level ${s.level} · ${s.lines.length} lines · ${s.provider}${s.model && s.model !== "-" ? " (" + s.model + ")" : ""} · ${fmtDate(s.created)}${s.usage && s.usage.output_tokens ? " · " + (s.usage.output_tokens / 1000).toFixed(1) + "k output tokens" : ""}`;

  $("#btn-save").disabled = true;
  $("#save-state").textContent = "";

  const list = $("#story-lines");
  list.replaceChildren(...s.lines.map((ln) => {
    const issues = state.validation.lines[String(ln.n)] || [];
    const cls = "line" + (issues.some((i) => i.level === "error") ? " has-error" : issues.length ? " has-warn" : "");
    const body = el("div", {},
      editable("primary-t", ln.primary, markDirty),
      editable("hanzi", ln.hanzi, markDirty),
      editable("english", ln.english, markDirty));
    if (issues.length) {
      body.append(el("div", { class: "issues" }, issues.map((i) => {
        const row = el("div", { class: i.level === "error" ? "i-err" : "i-warn" }, i.msg);
        if (s.track === "pinyin" && i.level === "error" && ["syllable_mismatch", "extra_pinyin", "tone_numbers"].includes(i.code)) {
          row.append(el("button", { type: "button", onclick: () => repairLine(ln.n) }, "Rebuild pinyin from hanzi"));
        }
        return row;
      })));
    }
    return el("li", { class: cls, "data-n": ln.n }, el("div", { class: "n", text: String(ln.n) }), body);
  }));
  renderCheckBar();
}

function renderCheckBar() {
  const v = state.validation;
  const bar = $("#check-bar");
  const problems = v.errors + v.warnings;
  bar.className = "check-bar" + (problems ? " bad" : "");
  const msg = problems
    ? `${v.errors} error${v.errors === 1 ? "" : "s"} and ${v.warnings} note${v.warnings === 1 ? "" : "s"} to review. Lines are marked below.`
    : "Every line passes the checks (pinyin matches hanzi, simplified characters, no gaps).";
  const filter = el("label", {}, el("input", { type: "checkbox", id: "only-problems" }), "Only lines with problems");
  bar.replaceChildren(el("span", { text: msg }), problems ? filter : "");
  const cb = $("#only-problems");
  if (cb) cb.addEventListener("change", () => {
    for (const li of $$("#story-lines .line")) li.hidden = cb.checked && !(li.classList.contains("has-error") || li.classList.contains("has-warn"));
  });
}

function collectEdit() {
  const t = $$("#story-title .f").map((n) => n.textContent.trim());
  const lines = $$("#story-lines .line").map((li, i) => {
    const [p, h, e] = $$(".f", li).map((n) => n.textContent.trim());
    return { n: i + 1, primary: p, hanzi: h, english: e };
  });
  return { title: { primary: t[0], hanzi: t[1], english: t[2] }, lines };
}

async function saveStory() {
  $("#btn-save").disabled = true;
  $("#save-state").textContent = "Saving...";
  try {
    const data = await api("/api/stories/" + state.story.id, { method: "PUT", body: collectEdit() });
    state.story = data.story; state.validation = data.validation; state.dirty = false;
    renderStory();
    $("#save-state").textContent = "Saved";
    loadLibraryCount();
  } catch (e) {
    $("#save-state").textContent = "Could not save: " + e.message;
    $("#btn-save").disabled = false;
  }
}

async function repairLine(n) {
  if (state.dirty) await saveStory();
  try {
    const data = await api(`/api/stories/${state.story.id}/lines/${n}/repair`, { method: "POST" });
    state.story = data.story; state.validation = data.validation;
    renderStory();
    $(`#story-lines [data-n="${n}"]`)?.scrollIntoView({ block: "center" });
  } catch (e) { alert(e.message); }
}

$("#btn-save").addEventListener("click", saveStory);
$("#btn-back").addEventListener("click", () => {
  if (state.dirty && !confirm("You have unsaved changes. Leave without saving?")) return;
  showView("library");
});
$("#btn-delete").addEventListener("click", async () => {
  if (!confirm("Delete this story permanently?")) return;
  try { await api("/api/stories/" + state.story.id, { method: "DELETE" }); state.story = null; await loadLibraryCount(); showView("library"); }
  catch (e) { alert(e.message); }
});
window.addEventListener("beforeunload", (e) => { if (state.dirty) { e.preventDefault(); e.returnValue = ""; } });
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "s" && !$("#view-story").hidden) { e.preventDefault(); if (state.dirty) saveStory(); }
});

/* ------------------------------------------------------------------ exports */
function onClick(sel, fn) { $(sel).addEventListener("click", (e) => { e.preventDefault(); if (state.story) fn(state.story.id); }); }
onClick("#btn-pdf", (id) => previewPdf(`/api/stories/${id}/pdf`));
onClick("#btn-pdf-dl", (id) => saveFile(`/api/stories/${id}/pdf?download=true`));
onClick("#btn-json", (id) => { $(".more").open = false; saveFile(`/api/stories/${id}/json`); });

/* ------------------------------------------------------------------ connections */
function renderProviders() {
  $("#providers").replaceChildren(...state.config.providers.map((p) => {
    const result = el("div", { class: "result" });
    const btn = el("button", { class: "ghost", type: "button", onclick: async () => {
      btn.disabled = true; btn.textContent = "Testing...";
      result.className = "result"; result.textContent = "";
      try {
        const r = await api("/api/providers/test", { method: "POST", body: { provider: p.id, model: recall("model." + p.id, "") || null } });
        result.className = "result " + (r.ok ? "good" : "bad");
        result.textContent = r.ok ? `Connected. Model ${r.model} answered in ${r.seconds}s.` : r.error;
      } catch (e) { result.className = "result bad"; result.textContent = e.message; }
      btn.disabled = false; btn.textContent = "Test connection";
    } }, "Test connection");
    const status = p.id === "mock" ? "Always available" : p.configured ? (p.key_env ? "Key found" : "Ready") : p.key_env ? `No key. Set ${p.key_env} on the backend` : "Not available here";
    return el("li", { class: "prov" },
      el("div", {}, el("div", { class: "name", text: p.label }), el("div", { class: "state" + (p.configured ? " ok" : ""), text: `${status} · default model ${p.model}` })),
      btn,
      p.note ? el("div", { class: "note", text: p.note }) : null,
      result);
  }));
}

init().catch((e) => {
  const local = ["localhost", "127.0.0.1", "[::1]", ""].includes(location.hostname);
  const hint = !API_BASE && !local ? " The backend address is not set yet: put it in frontend/config.js and redeploy." : "";
  document.body.prepend(el("p", { class: "error", style: "padding:16px", text: "Could not load the app: " + e.message + hint }));
});
