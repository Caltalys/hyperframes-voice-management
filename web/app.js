// VO Studio — SPA M3+M4.5. Vanilla JS, gọi API cùng origin.

const state = {
  ep: null, project: null, selectedFrame: null, defaultGap: 0.4,
  focusId: null,           // fragment đang focus (điều hướng phím)
  marked: new Set(),       // fragment đánh dấu khi nghe (client-side, mất khi reload)
  generating: new Set(),   // fragment đang generate (theo SSE)
  jobId: null,             // job đang chạy/mới nhất (để cancel)
};
let audioEl = null;

// ---------- API helpers ----------
async function api(method, path, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(path, opt);
  if (!r.ok) {
    let msg = r.status + "";
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.status === 204 ? null : r.json();
}
const getJSON = (p) => api("GET", p);
const postJSON = (p, b) => api("POST", p, b);
const putJSON = (p, b) => api("PUT", p, b);

const el = (tag, attrs = {}, children = []) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) e.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c) e.append(c);
  return e;
};

function toast(msg, isErr = false) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), 3200);
}

// ---------- tra cứu ----------
const currentLine = () =>
  state.project?.lines.find((l) => l.frame === state.selectedFrame) || null;
const activeFrags = (line) => line.fragments.filter((f) => !f.orphan);
const findFragment = (fid) => {
  for (const line of state.project?.lines || [])
    for (const f of line.fragments) if (f.id === fid) return f;
  return null;
};
const selectedTake = (frag) =>
  frag.takes.find((t) => t.id === frag.selected_take_id) || null;
const takeUrl = (take) =>
  "/api/takes/audio?ep=" + encodeURIComponent(state.ep) +
  "&take_wav=" + encodeURIComponent(take.wav);
const fragCard = (fid) =>
  document.querySelector(`.fragment[data-fid="${CSS.escape(fid)}"]`);
const staleIds = () => {
  const ids = [];
  for (const line of state.project?.lines || [])
    for (const f of line.fragments) if (!f.orphan && f.stale) ids.push(f.id);
  return ids;
};

// ---------- load / render ----------
async function loadState(ep) {
  const data = await getJSON("/api/projects/state?ep=" + encodeURIComponent(ep));
  state.ep = data.ep;
  state.project = data.project;
  document.getElementById("ep-input").value = data.ep;
  document.getElementById("btn-export-meta").disabled = false;
  document.getElementById("btn-export-script").disabled = false;
  document.getElementById("btn-reimport").disabled = false;
  if (state.selectedFrame == null && state.project.lines.length)
    state.selectedFrame = state.project.lines[0].frame;
  render();
}

function render() {
  renderRail();
  renderMain();
  applyDynamicState();
}

function lineStatus(line) {
  const frags = activeFrags(line);
  const sel = frags.filter((f) => f.has_selected).length;
  if (line.merged) return { cls: "ok", text: "merged ✓" };
  if (line.ready_to_merge) return { cls: "ready", text: "sẵn sàng" };
  return { cls: "", text: `${sel}/${frags.length}` };
}

function renderRail() {
  const rail = document.getElementById("rail");
  rail.innerHTML = "";
  if (!state.project) return;
  for (const line of state.project.lines) {
    const st = lineStatus(line);
    const stale = line.fragments.some((f) => !f.orphan && f.stale);
    const marked = line.fragments.filter((f) => state.marked.has(f.id)).length;
    rail.append(
      el("div", {
        class: "line-item" + (line.frame === state.selectedFrame ? " active" : ""),
        onclick: () => { state.selectedFrame = line.frame; state.focusId = null; render(); },
      }, [
        el("div", { class: "lh" }, [
          el("span", { class: "frame", text: "Line " + line.frame }),
          el("span", { class: "badge " + st.cls, text: st.text }),
        ]),
        el("div", { class: "title", text: line.title || "" }),
        stale ? el("span", { class: "badge warn", text: "⚠ text đổi" }) : null,
        marked ? el("span", { class: "badge mark", text: "🔖 " + marked }) : null,
      ])
    );
  }
}

function renderMain() {
  const main = document.getElementById("main");
  const scroll = main.scrollTop;
  main.innerHTML = "";
  if (!state.project || state.selectedFrame == null) {
    main.append(el("div", { class: "main-empty muted", text: "Chọn một line ở cột trái." }));
    return;
  }
  const line = currentLine();
  if (!line) return;
  const active = activeFrags(line);
  const playable = active.some((f) => selectedTake(f));

  main.append(
    el("div", { class: "line-head" }, [
      el("h2", { text: `Line ${line.frame}${line.title ? " — " + line.title : ""}` }),
      el("button", {
        id: "btn-play-line", class: "ghost", text: "▶ Nghe line",
        disabled: playable ? null : "true",
        title: "phát tuần tự take đã chọn, chèn gap — Space",
        onclick: () => playback.active ? stopLinePlayback() : playLineFrom(state.focusId),
      }),
      el("button", {
        text: "▶ Merge line",
        disabled: line.ready_to_merge ? null : "true",
        onclick: () => mergeLine(line.frame),
      }),
      el("button", { class: "ghost", text: "↻ Gen fragment thiếu",
        onclick: () => generate({ frame: line.frame }) }),
      el("button", { id: "btn-gen-marked", class: "ghost hidden",
        title: "generate mọi fragment đã đánh dấu (M) trong toàn project",
        onclick: genMarked }),
    ])
  );
  const sub = [line.time_range, line.delivery].filter(Boolean).join("  ·  ");
  main.append(el("div", { class: "line-sub", text: sub || "" }));
  if (line.merged)
    main.append(el("div", { class: "line-sub muted",
      text: `đã merge → ${line.merged.wav} (${line.merged.duration_s}s, ${line.merged.words.length} từ)` }));

  active.forEach((frag, i) => main.append(renderFragment(frag, i === active.length - 1)));

  // orphan (ẩn sau re-import) — hiện mờ cuối line, khôi phục được
  const orphans = line.fragments.filter((f) => f.orphan);
  if (orphans.length) {
    main.append(el("div", { class: "orphan-head muted",
      text: `${orphans.length} fragment orphan (không còn trong SCRIPT.md — take giữ nguyên):` }));
    for (const f of orphans)
      main.append(el("div", { class: "orphan-row" }, [
        el("span", { class: "muted", text: f.text }),
        el("button", { class: "ghost", text: "↩ Khôi phục",
          onclick: () => restoreFragment(f.id) }),
      ]));
  }
  main.scrollTop = scroll;
}

function renderFragment(frag, isLast) {
  const textArea = el("textarea", { class: "frag-text" });
  textArea.value = frag.text;
  textArea.addEventListener("blur", () => {
    if (textArea.value.trim() && textArea.value.trim() !== frag.text) editText(frag.id, textArea.value.trim());
  });

  const gapInput = el("input", { class: "gap", type: "number", step: "0.05", min: "0",
    placeholder: state.defaultGap, value: frag.gap_s ?? "" });
  gapInput.addEventListener("change", () => editGap(frag.id, gapInput.value));

  const card = el("div", {
    class: "fragment" + (frag.stale ? " stale" : ""),
    "data-fid": frag.id,
    onclick: () => { if (state.focusId !== frag.id) { state.focusId = frag.id; applyDynamicState(); } },
  }, [
    el("div", { class: "frag-top" }, [
      textArea,
      el("div", { class: "frag-meta" }, [
        el("label", { text: "gap sau (s)" }),
        el("div", { class: "gap-row" }, [
          gapInput,
          el("span", { class: "muted", text: "mặc định " + state.defaultGap }),
        ]),
      ]),
    ]),
    el("div", { class: "frag-actions" }, [
      el("span", { class: "frag-id", text: frag.id }),
      frag.stale ? el("span", { class: "badge warn", text: "⚠ take lệch text hiện tại" }) : null,
      el("span", { class: "badge mark hidden", text: "🔖 cần gen lại" }),
      el("span", { class: "badge gen hidden", text: "⏳ đang tạo…" }),
      el("button", { class: "btn-gen", text: "↻ Generate",
        onclick: () => generate({ fragment_ids: [frag.id] }) }),
      frag.takes.length === 2 ? el("button", { class: "ghost", text: "▶ A/B",
        title: "phát take 1 rồi take 2 liền nhau để so — phím A",
        onclick: () => playAB(frag.id) }) : null,
      el("button", { class: "ghost", text: "✂ Split", title: "tách tại vị trí con trỏ trong ô text",
        onclick: () => splitFragment(frag.id, textArea.selectionStart) }),
      isLast ? null : el("button", { class: "ghost", text: "⌄ Gộp dưới",
        onclick: () => mergeNext(frag.id) }),
    ]),
    renderTakes(frag),
  ]);
  return card;
}

function renderTakes(frag) {
  const wrap = el("div", { class: "takes" });
  if (!frag.takes.length) {
    wrap.append(el("div", { class: "take-empty", text: "chưa có take — bấm Generate" }));
    return wrap;
  }
  for (const take of frag.takes) {
    const selected = take.id === frag.selected_take_id;
    const canvas = el("canvas", { width: 220, height: 46 });
    const wavUrl = takeUrl(take);
    const wordEls = take.words.map((w) =>
      el("span", { class: "word", text: w.text, "data-start": w.start, "data-end": w.end }));

    wrap.append(el("div", { class: "take" + (selected ? " selected" : "") }, [
      el("div", { class: "take-head" }, [
        el("input", { type: "radio", name: "take-" + frag.id, checked: selected ? "true" : null,
          onchange: () => selectTake(frag.id, take.id) }),
        el("span", { class: "tid", text: take.id }),
        el("span", { class: "muted", text: `${take.duration_s}s` }),
        el("button", { class: "ghost", text: "▶", onclick: () => playTake(wavUrl, wordEls) }),
      ]),
      canvas,
      el("div", { class: "words" }, wordEls),
    ]));
    drawWaveform(canvas, wavUrl);
  }
  return wrap;
}

// Patch class/badge theo state động (focus/mark/generating/playing) mà KHÔNG
// re-render — giữ nguyên word highlight + audio đang chạy khi nghe cả line.
function applyDynamicState() {
  for (const card of document.querySelectorAll(".fragment[data-fid]")) {
    const fid = card.dataset.fid;
    card.classList.toggle("focused", fid === state.focusId);
    card.classList.toggle("marked", state.marked.has(fid));
    card.classList.toggle("generating", state.generating.has(fid));
    card.classList.toggle("playing", playback.active && fid === playback.playingId);
    card.querySelector(".badge.mark")?.classList.toggle("hidden", !state.marked.has(fid));
    card.querySelector(".badge.gen")?.classList.toggle("hidden", !state.generating.has(fid));
    const genBtn = card.querySelector(".btn-gen");
    if (genBtn) genBtn.disabled = state.generating.has(fid);
  }
  const playBtn = document.getElementById("btn-play-line");
  if (playBtn)
    playBtn.textContent = playback.active && !playback.paused ? "■ Dừng" : "▶ Nghe line";
  const genMarkedBtn = document.getElementById("btn-gen-marked");
  if (genMarkedBtn) {
    genMarkedBtn.classList.toggle("hidden", !state.marked.size);
    genMarkedBtn.textContent = `↻ Gen đánh dấu (${state.marked.size})`;
  }
  const stale = staleIds();
  const genStaleBtn = document.getElementById("btn-gen-stale");
  genStaleBtn.classList.toggle("hidden", !stale.length);
  genStaleBtn.textContent = `↻ Gen stale (${stale.length})`;
}

// ---------- nghe cả line (playlist + gap client-side) ----------
const playback = { active: false, paused: false, seq: [], i: 0, timer: null, playingId: null };

function playLineFrom(startFid) {
  const line = currentLine();
  if (!line) return;
  const seq = activeFrags(line).filter((f) => selectedTake(f));
  if (!seq.length) { toast("Line chưa có take nào được chọn.", true); return; }
  const start = startFid ? seq.findIndex((f) => f.id === startFid) : 0;
  playback.active = true;
  playback.paused = false;
  playback.seq = seq;
  playback.i = start >= 0 ? start : 0;
  playFragmentAt(playback.i);
}

function stopLinePlayback() {
  playback.active = false;
  playback.paused = false;
  playback.playingId = null;
  clearTimeout(playback.timer);
  if (audioEl) audioEl.pause();
  applyDynamicState();
}

function playFragmentAt(i) {
  if (!playback.active || i >= playback.seq.length) { stopLinePlayback(); return; }
  playback.i = i;
  const frag = playback.seq[i];
  playback.playingId = frag.id;
  applyDynamicState();
  fragCard(frag.id)?.scrollIntoView({ block: "nearest", behavior: "smooth" });

  // word highlight trên take đã chọn (nếu render còn đó — re-render giữa chừng chỉ mất highlight)
  const wordEls = [...(fragCard(frag.id)?.querySelectorAll(".take.selected .word") || [])];
  const gap = (frag.gap_s ?? state.defaultGap) * 1000;
  playUrl(takeUrl(selectedTake(frag)), wordEls, () => {
    if (!playback.active) return;
    if (playback.paused) { playback.i = i + 1; return; }  // resume sẽ phát tiếp
    playback.timer = setTimeout(() => playFragmentAt(i + 1), gap);
  });
}

function togglePlayback() {
  if (!playback.active) { playLineFrom(state.focusId); return; }
  if (playback.paused) {
    playback.paused = false;
    if (audioEl && audioEl.src && !audioEl.ended && audioEl.currentTime > 0) {
      audioEl.play().catch(() => {});
      applyDynamicState();
    } else playFragmentAt(playback.i);
  } else {
    playback.paused = true;
    clearTimeout(playback.timer);
    if (audioEl) audioEl.pause();
    applyDynamicState();
  }
}

function toggleMark(fid) {
  if (!fid) return;
  state.marked.has(fid) ? state.marked.delete(fid) : state.marked.add(fid);
  applyDynamicState();
}

async function genMarked() {
  const ids = [...state.marked];
  if (!ids.length) return;
  state.marked.clear();
  await generate({ fragment_ids: ids });
  render();
}

// ---------- audio dùng chung ----------
function playUrl(wavUrl, wordEls, onended) {
  if (!audioEl) audioEl = new Audio();
  audioEl.pause();
  audioEl.onended = null;
  wordEls.forEach((w) => w.classList.remove("active"));
  audioEl.src = wavUrl;
  const tick = () => {
    const t = audioEl.currentTime;
    for (const w of wordEls) {
      const on = t >= parseFloat(w.dataset.start) && t < parseFloat(w.dataset.end);
      w.classList.toggle("active", on);
    }
    if (!audioEl.paused && !audioEl.ended) requestAnimationFrame(tick);
    else if (audioEl.ended) wordEls.forEach((w) => w.classList.remove("active"));
  };
  audioEl.onplay = () => requestAnimationFrame(tick);
  if (onended) audioEl.onended = onended;
  audioEl.play().catch(() => {});
}

function playTake(wavUrl, wordEls) {
  stopLinePlayback();           // nghe 1 take lẻ thì dừng playlist
  playUrl(wavUrl, wordEls);
}

// A/B: phát take 1 rồi take 2 liền nhau (so sánh tức thì, không bấm ▶ từng cái)
function playAB(fid) {
  const frag = findFragment(fid);
  if (!frag || frag.takes.length < 2) return;
  stopLinePlayback();
  const card = fragCard(fid);
  const takeEls = card ? [...card.querySelectorAll(".take")] : [];
  const playOne = (i) => {
    if (i >= 2) { takeEls.forEach((t) => t.classList.remove("ab-playing")); return; }
    takeEls.forEach((t, k) => t.classList.toggle("ab-playing", k === i));
    const wordEls = takeEls[i] ? [...takeEls[i].querySelectorAll(".word")] : [];
    playUrl(takeUrl(frag.takes[i]), wordEls, () => setTimeout(() => playOne(i + 1), 250));
  };
  playOne(0);
}

// ---------- phím tắt ----------
function moveFocus(delta) {
  const line = currentLine();
  if (!line) return;
  const frags = activeFrags(line);
  if (!frags.length) return;
  let i = frags.findIndex((f) => f.id === state.focusId);
  i = i < 0 ? (delta > 0 ? 0 : frags.length - 1)
            : Math.min(frags.length - 1, Math.max(0, i + delta));
  state.focusId = frags[i].id;
  applyDynamicState();
  fragCard(state.focusId)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function moveLine(delta) {
  if (!state.project) return;
  const lines = state.project.lines;
  let i = lines.findIndex((l) => l.frame === state.selectedFrame);
  i = Math.min(lines.length - 1, Math.max(0, (i < 0 ? 0 : i + delta)));
  if (lines[i].frame === state.selectedFrame) return;
  stopLinePlayback();
  state.selectedFrame = lines[i].frame;
  state.focusId = null;
  render();
}

function selectTakeByIndex(fid, idx) {
  const frag = fid && findFragment(fid);
  const take = frag?.takes[idx];
  if (take && take.id !== frag.selected_take_id) selectTake(fid, take.id);
}

function onKeydown(ev) {
  if (ev.target.matches("input, textarea, select") || ev.ctrlKey || ev.metaKey || ev.altKey) return;
  if (!state.project) return;
  switch (ev.key) {
    case " ": ev.preventDefault(); togglePlayback(); break;
    case "ArrowDown": ev.preventDefault(); moveFocus(1); break;
    case "ArrowUp": ev.preventDefault(); moveFocus(-1); break;
    case "ArrowRight": ev.preventDefault(); moveLine(1); break;
    case "ArrowLeft": ev.preventDefault(); moveLine(-1); break;
    case "Enter":
      if (state.focusId && !state.generating.has(state.focusId)) {
        ev.preventDefault();
        generate({ fragment_ids: [state.focusId] });
      }
      break;
    case "1": selectTakeByIndex(state.focusId, 0); break;
    case "2": selectTakeByIndex(state.focusId, 1); break;
    case "a": case "A":
      if (state.focusId) playAB(state.focusId);
      break;
    case "m": case "M":
      toggleMark(playback.active ? playback.playingId : state.focusId);
      break;
  }
}

// ---------- actions ----------
async function editText(fid, text) {
  try {
    await putJSON("/api/fragments/text", { ep: state.ep, fragment_id: fid, text });
    await loadState(state.ep);
  } catch (e) { toast("Sửa text lỗi: " + e.message, true); }
}
async function editGap(fid, val) {
  try {
    const body = { ep: state.ep, fragment_id: fid };
    if (val === "" || val === null) body.clear_gap = true; else body.gap_s = parseFloat(val);
    await putJSON("/api/fragments/text", body);
    await loadState(state.ep);
  } catch (e) { toast("Sửa gap lỗi: " + e.message, true); }
}
async function splitFragment(fid, charIndex) {
  const frag = findFragment(fid);
  if (frag?.takes.length &&
      !confirm(`Tách fragment sẽ XÓA ${frag.takes.length} take đã generate (ranh giới audio đổi).\nTiếp tục?`))
    return;
  try {
    const r = await postJSON("/api/fragments/split",
      { ep: state.ep, fragment_id: fid, char_index: charIndex });
    toast(`Tách → ${r.fragments.join(" + ")} (take cũ bị xóa)`);
    await loadState(state.ep);
  } catch (e) { toast("Split lỗi: " + e.message, true); }
}
async function mergeNext(fid) {
  const line = currentLine();
  const frags = line ? activeFrags(line) : [];
  const i = frags.findIndex((f) => f.id === fid);
  const nTakes = (frags[i]?.takes.length || 0) + (frags[i + 1]?.takes.length || 0);
  if (nTakes &&
      !confirm(`Gộp 2 fragment sẽ XÓA ${nTakes} take đã generate (ranh giới audio đổi).\nTiếp tục?`))
    return;
  try {
    await postJSON("/api/fragments/merge-next", { ep: state.ep, fragment_id: fid });
    toast("Đã gộp với fragment dưới (take cũ bị xóa)");
    await loadState(state.ep);
  } catch (e) { toast("Gộp lỗi: " + e.message, true); }
}
async function restoreFragment(fid) {
  try {
    await postJSON("/api/fragments/restore", { ep: state.ep, fragment_id: fid });
    toast("Đã khôi phục fragment (take còn nguyên)");
    await loadState(state.ep);
  } catch (e) { toast("Khôi phục lỗi: " + e.message, true); }
}
async function reimport() {
  try {
    const r = await postJSON("/api/projects/reimport", { ep: state.ep, confirm: false });
    const d = r.diff;
    if (!d.changed) { toast("SCRIPT.md không có gì thay đổi."); return; }
    const parts = [];
    if (d.lines_added.length) parts.push(`+ line mới: ${d.lines_added.join(", ")}`);
    if (d.lines_removed.length) parts.push(`− line biến mất (fragment thành orphan): ${d.lines_removed.join(", ")}`);
    for (const lc of d.lines_changed)
      parts.push(`~ line ${lc.frame}: giữ ${lc.kept}` +
        (lc.added.length ? `, thêm ${lc.added.length} fragment trống` : "") +
        (lc.orphaned.length ? `, ${lc.orphaned.length} thành orphan` : "") +
        (lc.restored ? `, khôi phục ${lc.restored}` : "") +
        (lc.meta_changed ? ", meta đổi" : ""));
    if (!confirm("Re-import SCRIPT.md — thay đổi:\n\n" + parts.join("\n") +
                 "\n\nFragment khớp text giữ nguyên take. Áp dụng?")) return;
    await postJSON("/api/projects/reimport", { ep: state.ep, confirm: true });
    toast("Re-import xong.");
    state.focusId = null;
    await loadState(state.ep);
  } catch (e) { toast("Re-import lỗi: " + e.message, true); }
}
async function cancelJob() {
  if (!state.jobId) return;
  try { await postJSON(`/api/jobs/${state.jobId}/cancel`); }
  catch (e) { toast("Hủy job lỗi: " + e.message, true); }
}
async function selectTake(fid, tid) {
  try {
    await postJSON("/api/takes/select", { ep: state.ep, fragment_id: fid, take_id: tid });
    await loadState(state.ep);
  } catch (e) { toast("Chọn take lỗi: " + e.message, true); }
}
async function generate(target) {
  try {
    const body = Object.assign({ ep: state.ep }, target);
    const r = await postJSON("/api/takes/generate", body);
    state.jobId = r.job_id;
    showJob(0, r.total, "đang tạo giọng…");
  } catch (e) { toast("Generate lỗi: " + e.message, true); }
}
async function mergeLine(frame) {
  try {
    const r = await postJSON("/api/lines/merge", { ep: state.ep, frame });
    toast(`Merge line ${frame}: ${r.wav} (${r.duration_s}s)`);
    await loadState(state.ep);
  } catch (e) { toast("Merge lỗi: " + e.message, true); }
}

// ---------- job bar + SSE ----------
function showJob(index, total, label) {
  const bar = document.getElementById("job-bar");
  bar.classList.remove("hidden");
  document.getElementById("job-fill").style.width = total ? (100 * index / total) + "%" : "0";
  document.getElementById("job-text").textContent = `${label} ${index}/${total}`;
}
function hideJob() { document.getElementById("job-bar").classList.add("hidden"); }

function connectSSE() {
  const es = new EventSource("/api/jobs/stream");
  es.onmessage = async (ev) => {
    const e = JSON.parse(ev.data);
    if (e.job_id || e.id) state.jobId = e.job_id || e.id;
    if (e.type === "fragment_start") {
      state.generating.add(e.fragment_id);
      showJob(e.index - 1, e.total, "đang tạo giọng…");
      applyDynamicState();
    } else if (e.type === "fragment_done") {
      state.generating.delete(e.fragment_id);
      showJob(e.index, e.total, "đang tạo giọng…");
      if (state.ep) await loadState(state.ep);   // take mới hiện ra
    } else if (e.type === "done") {
      state.generating.clear();
      showJob(e.total, e.total, "xong");
      setTimeout(hideJob, 900);
      if (state.ep) await loadState(state.ep);
    } else if (e.type === "canceled") {
      state.generating.clear();
      toast(`Đã hủy job (${e.index}/${e.total})`);
      hideJob();
      if (state.ep) await loadState(state.ep);   // take đã xong trước khi hủy vẫn còn
    } else if (e.type === "error") {
      state.generating.clear();
      toast("Job lỗi: " + (e.error || ""), true);
      hideJob();
      applyDynamicState();
    }
  };
  es.onerror = () => { /* EventSource tự kết nối lại */ };
}

// ---------- init ----------
async function init() {
  try {
    const cfg = await getJSON("/api/config");
    state.defaultGap = cfg.default_gap_s;
    document.getElementById("voice-label").textContent = "voice: " + cfg.voice + " (global)";
  } catch {}
  try {
    const rec = await getJSON("/api/projects/recent");
    const dl = document.getElementById("recent-list");
    for (const p of rec.recent_projects) dl.append(el("option", { value: p }));
    if (rec.recent_projects[0]) document.getElementById("ep-input").value = rec.recent_projects[0];
  } catch {}

  document.getElementById("btn-open").addEventListener("click", async () => {
    const ep = document.getElementById("ep-input").value.trim();
    if (!ep) return;
    try { await postJSON("/api/projects/open", { ep }); state.selectedFrame = null; await loadState(ep); }
    catch (e) { toast("Mở lỗi: " + e.message, true); }
  });
  document.getElementById("btn-import").addEventListener("click", async () => {
    const ep = document.getElementById("ep-input").value.trim();
    if (!ep) return;
    try {
      const r = await postJSON("/api/projects/import", { ep });
      toast(`Import: ${r.lines} line, ${r.fragments} fragment`);
      state.selectedFrame = null; await loadState(ep);
    } catch (e) {
      if (String(e.message).includes("đã tồn tại")) toast("Đã có project — bấm Mở.", true);
      else toast("Import lỗi: " + e.message, true);
    }
  });
  document.getElementById("btn-export-meta").addEventListener("click", async () => {
    try { const r = await postJSON("/api/export/audio-meta", { ep: state.ep });
      toast(`audio_meta: ${r.voices} voices` + (r.skipped_frames.length ? `, bỏ qua ${r.skipped_frames}` : "")); }
    catch (e) { toast("Export lỗi: " + e.message, true); }
  });
  document.getElementById("btn-export-script").addEventListener("click", async () => {
    try { await postJSON("/api/export/script", { ep: state.ep }); toast("Đã ghi SCRIPT.md"); }
    catch (e) { toast("Export lỗi: " + e.message, true); }
  });

  document.getElementById("btn-reimport").addEventListener("click", reimport);
  document.getElementById("btn-job-cancel").addEventListener("click", cancelJob);
  document.getElementById("btn-gen-stale").addEventListener("click", () => {
    const ids = staleIds();
    if (ids.length) generate({ fragment_ids: ids });
  });

  document.addEventListener("keydown", onKeydown);
  connectSSE();
}

init();
