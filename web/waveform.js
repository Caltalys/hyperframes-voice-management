// Vẽ waveform từ file wav bằng WebAudio (không thư viện ngoài).
// Cache theo URL để không decode lại khi re-render.

const _wfCache = new Map();
let _audioCtx = null;

function audioCtx() {
  if (!_audioCtx) _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  return _audioCtx;
}

async function drawWaveform(canvas, wavUrl) {
  try {
    let buf = _wfCache.get(wavUrl);
    if (!buf) {
      const resp = await fetch(wavUrl);
      const arr = await resp.arrayBuffer();
      buf = await audioCtx().decodeAudioData(arr);
      _wfCache.set(wavUrl, buf);
    }
    renderPeaks(canvas, buf);
  } catch (e) {
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#a1a1aa";
    ctx.font = "11px sans-serif";
    ctx.fillText("(không vẽ được waveform)", 6, canvas.height / 2);
  }
}

function renderPeaks(canvas, buf) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 220, h = canvas.clientHeight || 46;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);

  const data = buf.getChannelData(0);
  const step = Math.max(1, Math.floor(data.length / w));
  const mid = h / 2;
  ctx.strokeStyle = "#2563eb";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let x = 0; x < w; x++) {
    let min = 1, max = -1;
    for (let i = 0; i < step; i++) {
      const v = data[x * step + i] || 0;
      if (v < min) min = v;
      if (v > max) max = v;
    }
    ctx.moveTo(x + 0.5, mid + min * mid);
    ctx.lineTo(x + 0.5, mid + max * mid);
  }
  ctx.stroke();
}

window.drawWaveform = drawWaveform;
