// VO Studio — SPA M3. Vanilla JS, gọi API cùng origin.

const state = { ep: null, project: null, selectedFrame: null, defaultGap: 0.4 };
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

// ---------- load / render ----------
async function loadState(ep) {
  const data = await getJSON("/api/projects/state?ep=" + encodeURIComponent(ep));
  state.ep = data.ep;
  state.project = data.project;
  document.getElementById("ep-input").value = data.ep;
  document.getElementById("btn-export-meta").disabled = false;
  document.getElementById("btn-export-script").disabled = false;
  if (state.selectedFrame == null && state.project.lines.length)
    state.selectedFrame = state.project.lines[0].frame;
  render();
}

function render() {
  renderRail();
  renderMain();
}

function lineStatus(line) {
  const frags = line.fragments.filter((f) => !f.orphan);
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
    rail.append(
      el("div", {
        class: "line-item" + (line.frame === state.selectedFrame ? " active" : ""),
        onclick: () => { state.selectedFrame = line.frame; render(); },
      }, [
        el("div", { class: "lh" }, [
          el("span", { class: "frame", text: "Line " + line.frame }),
          el("span", { class: "badge " + st.cls, text: st.text }),
        ]),
        el("div", { class: "title", text: line.title || "" }),
        stale ? el("span", { class: "badge warn", text: "⚠ text đổi" }) : null,
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
  const line = state.project.lines.find((l) => l.frame === state.selectedFrame);
  if (!line) return;

  main.append(
    el("div", { class: "line-head" }, [
      el("h2", { text: `Line ${line.frame}${line.title ? " — " + line.title : ""}` }),
      el("button", {
        text: "▶ Merge line",
        disabled: line.ready_to_merge ? null : "true",
        onclick: () => mergeLine(line.frame),
      }),
      el("button", { class: "ghost", text: "↻ Gen fragment thiếu",
        onclick: () => generate({ frame: line.frame }) }),
    ])
  );
  const sub = [line.time_range, line.delivery].filter(Boolean).join("  ·  ");
  main.append(el("div", { class: "line-sub", text: sub || "" }));
  if (line.merged)
    main.append(el("div", { class: "line-sub muted",
      text: `đã merge → ${line.merged.wav} (${line.merged.duration_s}s, ${line.merged.words.length} từ)` }));

  for (const frag of line.fragments) {
    if (frag.orphan) continue;
    main.append(renderFragment(frag));
  }
  main.scrollTop = scroll;
}

function renderFragment(frag) {
  const textArea = el("textarea", { class: "frag-text" });
  textArea.value = frag.text;
  textArea.addEventListener("blur", () => {
    if (textArea.value.trim() && textArea.value.trim() !== frag.text) editText(frag.id, textArea.value.trim());
  });

  const gapInput = el("input", { class: "gap", type: "number", step: "0.05", min: "0",
    placeholder: state.defaultGap, value: frag.gap_s ?? "" });
  gapInput.addEventListener("change", () => editGap(frag.id, gapInput.value));

  const card = el("div", { class: "fragment" + (frag.stale ? " stale" : "") }, [
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
      el("button", { text: "↻ Generate", onclick: () => generate({ fragment_ids: [frag.id] }) }),
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
    const wavUrl = "/api/takes/audio?ep=" + encodeURIComponent(state.ep) +
      "&take_wav=" + encodeURIComponent(take.wav);
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

function playTake(wavUrl, wordEls) {
  if (!audioEl) audioEl = new Audio();
  audioEl.pause();
  wordEls.forEach((w) => w.classList.remove("active"));
  audioEl.src = wavUrl;
  const tick = () => {
    const t = audioEl.currentTime;
    for (const w of wordEls) {
      const on = t >= parseFloat(w.dataset.start) && t < parseFloat(w.dataset.end);
      w.classList.toggle("active", on);
    }
    if (!audioEl.paused && !audioEl.ended) requestAnimationFrame(tick);
    else wordEls.forEach((w) => w.classList.remove("active"));
  };
  audioEl.play().then(() => requestAnimationFrame(tick)).catch(() => {});
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
    if (e.type === "fragment_start") showJob(e.index - 1, e.total, "đang tạo giọng…");
    else if (e.type === "fragment_done") {
      showJob(e.index, e.total, "đang tạo giọng…");
      if (state.ep) await loadState(state.ep);   // take mới hiện ra
    } else if (e.type === "done") {
      showJob(e.total, e.total, "xong");
      setTimeout(hideJob, 900);
      if (state.ep) await loadState(state.ep);
    } else if (e.type === "error") {
      toast("Job lỗi: " + (e.error || ""), true);
      hideJob();
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

  connectSSE();
}

init();
