"use strict";
const $ = (id) => document.getElementById(id);
const PAGE = 60;
const LAST = 30;

const state = {
  items: [],          // camera-roll order, newest saved first
  total: 0,
  loading: false,
  selected: new Set(), // shortcodes
  anchor: null,        // index of the last tile picked, for shift-click ranges
  open: -1,            // index shown in the viewer
  actions: { sync: false, pull: false },
  jobSeen: null,
};

// -- helpers -------------------------------------------------------------------

function h(tag, props, ...kids) {
  const el = Object.assign(document.createElement(tag), props || {});
  el.append(...kids.filter((k) => k != null));
  return el;
}

async function api(path, body) {
  const r = await fetch(path, body === undefined ? undefined : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(data.error || r.statusText), { data });
  return data;
}

let toastTimer;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { /* fall through */ }
  const ta = h("textarea", { value: text });
  ta.style.cssText = "position:fixed;opacity:0";
  document.body.append(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch { /* denied */ }
  ta.remove();
  return ok;
}

const clock = (s) => s == null ? "" : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
const BADGE = {
  done: ["", "Transcript ready"],
  pending: ["", "Not transcribed yet"],
  failed: ["failed", "Transcription failed"],
  none: ["", "No speech"],
};

// -- grid ----------------------------------------------------------------------

function tile(item, i) {
  const [label, title] = BADGE[item.transcript_status] || BADGE.pending;
  const placeholder = () => h("div", { className: "ph" },
    h("b", {}, item.kind === "image" || item.kind === "carousel" ? "▣" : "▶"),
    h("span", {}, item.author ? "@" + item.author : item.shortcode));
  let picture = placeholder();
  if (item.has_thumb) {
    picture = h("img", { loading: "lazy", alt: "", draggable: false,
                         src: `/media/${item.shortcode}/thumb.jpg` });
    picture.onerror = () => picture.replaceWith(placeholder());
  }
  const el = h("div", { className: "tile", tabIndex: 0 },
    picture,
    h("button", { className: "pick", title: "Select" }),
    h("span", { className: `badge ${item.transcript_status}`, title }, h("i"), label || null),
    h("span", { className: "dur" }, clock(item.duration)));
  el.dataset.i = i;
  el.setAttribute("aria-label", `${item.author ? "@" + item.author : item.shortcode}. ${title}`);
  el.classList.toggle("sel", state.selected.has(item.shortcode));
  return el;
}

async function loadMore() {
  if (state.loading || (state.items.length >= state.total && state.total !== -1)) return;
  state.loading = true;
  try {
    const page = await api(`/api/items?limit=${PAGE}&offset=${state.items.length}`);
    state.total = page.total;
    state.toPull = page.to_pull || 0;
    const start = state.items.length;
    state.items.push(...page.items);
    $("grid").append(...page.items.map((it, n) => tile(it, start + n)));
    if (!page.items.length) state.total = state.items.length;
  } catch (e) {
    toast(`Could not load the library: ${e.message}`);
    state.total = state.items.length;
  } finally {
    state.loading = false;
  }
  paint();
  // Keep going until the sentinel is pushed off screen.
  if (state.items.length < state.total && $("more").getBoundingClientRect().top < innerHeight + 600) loadMore();
}

async function reload() {
  state.items = [];
  state.total = -1;
  state.anchor = null;
  $("grid").replaceChildren();
  await loadMore();
}

function paint() {
  const n = state.selected.size;
  $("count").textContent = state.total > 0 ? plural(state.total, "saved video") : "";
  $("empty").hidden = state.total !== 0;
  $("last30").disabled = state.total <= 0;
  $("last30").textContent = `Last ${LAST}`;
  $("clear").hidden = n === 0;
  for (const id of ["free", "remove", "unsave"]) $(id).hidden = n === 0;
  $("freeOld").hidden = n > 0 || state.total <= 0;
  $("copy").disabled = n === 0;
  $("copy").textContent = n ? `Copy merged transcripts (${n})` : "Copy merged transcripts";
  $("grid").classList.toggle("picking", n > 0);
  for (const el of $("grid").children) {
    el.classList.toggle("sel", state.selected.has(state.items[el.dataset.i].shortcode));
  }
  if (state.open >= 0) paintViewerSelect();
}

function toggle(i, range) {
  const code = state.items[i].shortcode;
  if (range && state.anchor != null) {
    const [a, b] = [Math.min(state.anchor, i), Math.max(state.anchor, i)];
    for (let k = a; k <= b; k++) state.selected.add(state.items[k].shortcode);
  } else if (state.selected.has(code)) {
    state.selected.delete(code);
  } else {
    state.selected.add(code);
  }
  state.anchor = i;
  paint();
}

$("grid").addEventListener("click", (e) => {
  const el = e.target.closest(".tile");
  if (!el) return;
  const i = +el.dataset.i;
  if (e.target.closest(".pick") || e.shiftKey || e.ctrlKey || e.metaKey) toggle(i, e.shiftKey);
  else openViewer(i);
});
$("grid").addEventListener("keydown", (e) => {
  const el = e.target.closest(".tile");
  if (!el || e.target !== el) return;
  if (e.key === "Enter") openViewer(+el.dataset.i);
  if (e.key === " ") { e.preventDefault(); toggle(+el.dataset.i, e.shiftKey); }
});

$("last30").onclick = () => {
  state.selected = new Set(state.items.slice(0, LAST).map((it) => it.shortcode));
  state.anchor = null;
  paint();
  toast(`Selected the ${plural(state.selected.size, "newest video")}`);
};
$("clear").onclick = () => { state.selected.clear(); state.anchor = null; paint(); };

async function copyMerged(codes, what) {
  try {
    const m = await api("/api/merged", codes);
    if (!m.count) return toast("Nothing to copy");
    const ok = await copyText(m.text);
    const gap = m.without_transcript ? ` (${m.without_transcript} without a transcript yet)` : "";
    toast(ok ? `Copied ${what || plural(m.count, "transcript")}${gap}` : "The browser blocked the clipboard");
  } catch (e) {
    toast(`Copy failed: ${e.message}`);
  }
}
$("copy").onclick = () => copyMerged([...state.selected]);

new IntersectionObserver((es) => es.some((x) => x.isIntersecting) && loadMore(),
  { rootMargin: "800px" }).observe($("more"));

// -- viewer --------------------------------------------------------------------

function paintViewerSelect() {
  const on = state.selected.has(state.items[state.open].shortcode);
  $("vSelect").textContent = on ? "Selected ✓" : "Select";
  $("vSelect").classList.toggle("primary", on);
}

// -- one post at a time: download on open ----------------------------------------
//
// Nothing is downloaded until a post is opened. Opening one that is not on
// this computer fetches and transcribes just that post, after a short pause so
// that flicking through with the arrow keys does not download every post passed.

const DWELL_MS = 1200;
let dwellTimer;
let fetching = null; // shortcode of the post being downloaded for the viewer

function paintStage(i, note) {
  const it = state.items[i];
  const src = `/media/${it.shortcode}`;
  if (it.has_video) {
    $("vStage").replaceChildren(h("video", { src: `${src}/video.mp4`, controls: true, autoplay: true,
      playsInline: true, poster: it.has_thumb ? `${src}/thumb.jpg` : "" }));
    return;
  }
  const busy = fetching === it.shortcode;
  const why = note ? note
    : busy ? "Downloading…"
    : it.media_status === "failed" ? "Download failed" + (it.error ? `: ${it.error}` : "")
    : it.media_status === "none" ? "No video for this post"
    : it.media_status === "freed" ? "Video freed to save space."
    : "Not on this computer yet.";
  const box = h("div", { className: "note" }, why);
  if (!busy && it.media_status !== "none") {
    const b = h("button", {}, it.media_status === "pending" ? "Download" : "Download again");
    b.onclick = () => fetchOne(it.shortcode);
    box.append(" ", b);
  }
  $("vStage").replaceChildren(
    it.has_thumb ? h("img", { src: `${src}/thumb.jpg`, alt: "" }) : h("div", { className: "blank" }, "▶"),
    box);
}

async function loadTranscript(i) {
  const it = state.items[i];
  const status = { pending: "not transcribed yet", failed: "failed", none: "no speech" }[it.transcript_status];
  try {
    const full = await api(`/api/items/${it.shortcode}`);
    if (state.open !== i) return;
    $("vTranscript").textContent = full.transcript || "";
    $("vStatus").textContent = full.transcript ? ""
      : fetching === it.shortcode && it.has_video ? "transcribing…" : status || "empty";
    if (it.transcript_status === "failed" && full.error) $("vStatus").textContent = `failed: ${full.error}`;
  } catch (e) {
    if (state.open === i) $("vStatus").textContent = `could not load (${e.message})`;
  }
}

// Take a fresh copy of one post from the server into the roll and the viewer.
async function refreshOne(shortcode) {
  const i = state.items.findIndex((it) => it.shortcode === shortcode);
  if (i < 0) return null;
  const had = state.items[i].has_video;
  const full = await api(`/api/items/${shortcode}`);
  delete full.transcript;
  Object.assign(state.items[i], full);
  $("grid").children[i]?.replaceWith(tile(state.items[i], i));
  if (state.open === i) {
    if (!had || !state.items[i].has_video) paintStage(i); // never restart a video that is playing
    await loadTranscript(i);
  }
  return state.items[i];
}

async function fetchOne(shortcode) {
  const i = state.items.findIndex((it) => it.shortcode === shortcode);
  if (i < 0 || fetching) return;
  try {
    await api("/api/actions/pull", { shortcodes: [shortcode] });
  } catch (e) {
    // Something else is running (a Sync, a Pull, another download).
    if (state.open === i) paintStage(i, `Busy: ${e.message}. Try again in a moment.`);
    return;
  }
  fetching = shortcode;
  if (state.open === i) paintStage(i);
  try {
    for (;;) {
      await new Promise((r) => setTimeout(r, 1000));
      const { job } = await api("/api/actions");
      paintActions(job);
      const running = job && job.state === "running";
      if (!running) fetching = null;
      const it = await refreshOne(shortcode);
      if (!running) {
        if (job && job.state === "done") { state.jobSeen = job.started; paintActions(job); }
        else if (it && state.open === state.items.indexOf(it)) paintStage(state.open);
        break;
      }
    }
  } catch (e) {
    toast(`Lost track of the download: ${e.message}`);
  } finally {
    fetching = null;
    pollActions(false);
  }
}

async function openViewer(i) {
  if (i < 0 || i >= state.items.length) return;
  clearTimeout(dwellTimer);
  state.open = i;
  const it = state.items[i];
  paintStage(i);
  if (!it.has_video && it.media_status === "pending" && !fetching) {
    dwellTimer = setTimeout(() => { if (state.open === i) fetchOne(it.shortcode); }, DWELL_MS);
  }
  $("vAuthor").textContent = it.author ? "@" + it.author : it.shortcode;
  $("vAuthor").href = it.url;
  $("vAuthor").title = "Open on Instagram";
  const posted = it.taken_at ? new Date(it.taken_at * 1000).toLocaleDateString(undefined,
    { day: "numeric", month: "short", year: "numeric" }) : null;
  $("vMeta").textContent = [posted && `Posted ${posted}`, clock(it.duration), `${i + 1} of ${state.total}`]
    .filter(Boolean).join(" · ");
  $("vCaption").textContent = it.caption || "";
  $("vCaption").classList.toggle("dim", !it.caption);
  if (!it.caption) $("vCaption").textContent = "No caption";
  $("vStatus").textContent = "";
  $("vTranscript").textContent = "";
  $("vPrev").hidden = i === 0;
  $("vNext").hidden = i >= state.total - 1;
  $("viewer").hidden = false;
  document.body.style.overflow = "hidden";
  paintViewerSelect();
  if (i >= state.items.length - 2) loadMore();
  await loadTranscript(i);
}

function closeViewer() {
  if (state.open < 0) return;
  clearTimeout(dwellTimer);
  const i = state.open;
  state.open = -1;
  $("vStage").replaceChildren(); // stops playback
  $("viewer").hidden = true;
  document.body.style.overflow = "";
  $("grid").children[i]?.focus({ preventScroll: false });
}

$("vClose").onclick = closeViewer;
$("vPrev").onclick = () => openViewer(state.open - 1);
$("vNext").onclick = () => openViewer(state.open + 1);
$("vSelect").onclick = () => toggle(state.open, false);
$("vCopy").onclick = () => copyMerged([state.items[state.open].shortcode], "this transcript");
document.addEventListener("keydown", (e) => {
  if (state.open < 0) {
    if (e.key === "Escape" && state.selected.size) $("clear").click();
    return;
  }
  if (e.key === "Escape") closeViewer();
  else if (e.target.tagName === "VIDEO") return; // leave arrow keys to the player
  else if (e.key === "ArrowLeft") openViewer(state.open - 1);
  else if (e.key === "ArrowRight") openViewer(state.open + 1);
});

// -- Sync / Pull ---------------------------------------------------------------

const NAMES = { sync: "Sync", pull: "Pull" };
const JOBS = { ...NAMES, free: "Free video", remove: "Remove", unsave: "Unsave" };
const NOT_YET = {
  sync: "Sync isn't available yet: the sources track hasn't been merged in.",
  pull: "Pull isn't available yet: the pipeline track hasn't been merged in.",
};

function paintActions(job) {
  const running = job && job.state === "running";
  for (const name of Object.keys(NAMES)) {
    const b = $(name);
    const ok = state.actions[name];
    b.classList.toggle("na", !ok);
    b.setAttribute("aria-disabled", String(!ok));
    b.title = !ok ? NOT_YET[name]
      : name === "sync" ? "List new Instagram saved posts and fetch their thumbnails"
      : "Download and transcribe every post that is not on this computer yet";
    b.disabled = !!running;
    b.classList.toggle("busy", !!running && job.name === name);
    b.textContent = running && job.name === name ? `${NAMES[name]}…` : NAMES[name];
  }
  const bar = $("job");
  bar.hidden = !job || (job.state === "done" && state.jobSeen === job.started);
  if (job) {
    const last = job.lines[job.lines.length - 1];
    bar.className = `job ${job.state}`;
    $("jobText").textContent = `${JOBS[job.name]}: ` + (running ? last || "starting…"
      : job.state === "done" ? last || "finished" : `failed. ${last || `exit code ${job.returncode}`}`);
    $("jobText").title = job.lines.join("\n");
  }
}

let pollTimer;
async function pollActions(wasRunning) {
  clearTimeout(pollTimer);
  let data;
  try { data = await api("/api/actions"); } catch { pollTimer = setTimeout(() => pollActions(wasRunning), 3000); return; }
  state.actions = data.available;
  const job = data.job;
  paintActions(job);
  if (job && job.state === "running") {
    pollTimer = setTimeout(() => pollActions(true), 1000);
  } else if (wasRunning && job) {
    toast(job.state === "done" ? `${JOBS[job.name]} finished` : `${JOBS[job.name]} failed`);
    await reload();
    if (job.state === "done") setTimeout(() => { state.jobSeen = job.started; paintActions(job); }, 6000);
  }
}

for (const name of Object.keys(NAMES)) {
  $(name).onclick = async () => {
    if (!state.actions[name]) return toast(NOT_YET[name]);
    if (name === "pull" && state.toPull > 0 && !confirm(
      `Download and transcribe ${plural(state.toPull, "post")}?

That is roughly ${Math.round(state.toPull * 7).toLocaleString()} MB of video. To get just one, click it in the roll instead.`)) return;
    try {
      await api(`/api/actions/${name}`, {});
      pollActions(true);
    } catch (e) {
      toast(e.message);
      pollActions(false);
    }
  };
}

// -- Free video / Remove / Unsave ----------------------------------------------

async function runJob(name, opts) {
  try {
    await api(`/api/actions/${name}`, opts);
    state.selected.clear();
    state.anchor = null;
    closeViewer();
    paint();
    pollActions(true);
  } catch (e) {
    toast(e.message);
    pollActions(false);
  }
}

const ASK = {
  free: (n) => `Delete the video files of ${plural(n, "post")}?

Thumbnails, captions and transcripts stay, and the posts stay in the roll. You will not be able to play them here any more.`,
  remove: (n) => `Remove ${plural(n, "post")} from Magpie?

Their videos and transcripts are deleted from this computer. They stay saved on Instagram, and Sync will not bring them back.`,
  unsave: (n) => `Unsave ${plural(n, "post")} on Instagram?

This changes your Instagram account: they leave your Saved tab, and they are removed from Magpie too. Magpie sends one request per post, a few seconds apart.`,
};
for (const name of Object.keys(ASK)) {
  $(name).onclick = () => {
    const codes = [...state.selected];
    if (codes.length && confirm(ASK[name](codes.length))) runJob(name, { shortcodes: codes });
  };
}
$("freeOld").onclick = () => {
  const answer = prompt(`Keep the videos of how many of your newest saves?

Older posts keep their thumbnail, caption and transcript, but their video files are deleted.`, "100");
  if (answer == null) return;
  const keep = Number(answer);
  if (!Number.isInteger(keep) || keep < 0) return toast("Type a whole number");
  runJob("free", { keep });
};

pollActions(false);
reload();
