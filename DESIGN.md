# VO Studio — Thiết kế chi tiết

Web tool quản lý voiceover cho pipeline [hyperframes](https://github.com/heygen-com/hyperframes),
thay thế CLI `videos/tools/vo/vo.py` trong greencore-v2. Tạo/duyệt voiceover ở cấp **fragment**
(đơn vị nhỏ hơn line), giữ lịch sử take, merge thủ công thành line wav, export ra
`audio_meta.json` cho pipeline.

Trạng thái: **thiết kế** (2026-07-05). Chưa scaffold code.

---

## 1. Mục tiêu & phạm vi

**Mục tiêu:** thay `vo.py` bằng web tool review-centric, nơi voiceover được tạo/duyệt ở cấp
**fragment**, giữ lịch sử take, merge thủ công thành line wav, export ra `audio_meta.json`.

**Trong phạm vi:** import SCRIPT.md (bootstrap), quản lý line/fragment/take, generate TTS async,
align theo fragment, review + chọn take, merge line, export `audio_meta.json` + SCRIPT.md.

**Ngoài phạm vi (giữ nguyên pipeline hyperframes):** `audio.mjs sync-durations`,
`captions.mjs build`, `assemble-index.mjs`, BGM/SFX. Tool chỉ ghi `voices[]`, không đụng
`bgm`/`sfx`.

**Bất biến (hợp đồng đầu ra):**
```jsonc
// audio_meta.json — voices[] phải đúng format cũ
{ "frame": 3, "path": "assets/vo/03.wav", "duration_s": 12.4,
  "words": [{ "id": "w0", "text": "Nỗi", "start": 0.0, "end": 0.31 }, ...] }
```

---

## 2. Cấu trúc repo

```
hyperframes-voice-management/
├─ pyproject.toml            # deps: fastapi, uvicorn, vieneu, faster-whisper, numpy
├─ README.md
├─ DESIGN.md                 # (file này)
├─ config.default.json       # voice, model, gap mặc định (seed cho global config)
├─ app/
│  ├─ main.py                # FastAPI app, mount static, đăng ký routers
│  ├─ config.py              # đọc/ghi global config (~/.hyperframes-vo/config.json)
│  ├─ models.py              # pydantic schema: Project, Line, Fragment, Take
│  ├─ store.py               # load/save project.json (atomic write), lock
│  ├─ script_io.py           # import parser + export SCRIPT.md
│  ├─ engine/
│  │  ├─ tts.py              # bọc vieneu (lazy-load model), infer 1 fragment
│  │  ├─ align.py            # bọc faster-whisper, force_align 1 wav ngắn
│  │  └─ audio.py            # concat wav + trim lặng + tính offset (từ vo.py)
│  ├─ jobs.py                # in-process job queue + trạng thái + SSE stream
│  └─ routers/
│     ├─ projects.py         # mở/import/list project
│     ├─ lines.py            # CRUD line/fragment, split/merge fragment, sửa text
│     ├─ takes.py            # generate, align, chọn take, nghe
│     └─ export.py           # merge line, export audio_meta.json + SCRIPT.md
└─ web/
   ├─ index.html             # SPA 1 file (không build step)
   ├─ app.js                 # state, fetch API, SSE, render
   ├─ waveform.js            # WaveSurfer hoặc <audio> + canvas đơn giản
   └─ style.css
```

Engine (`tts.py`, `align.py`, `audio.py`) là **port trực tiếp** từ `vo.py` — logic đã kiểm chứng
(chunk theo câu, trim lặng `concat_wavs`, `force_align` với difflib giữ text SCRIPT.md không lấy
text whisper). Chỉ đổi đơn vị từ line → fragment.

---

## 3. Data model

### 3.1 Global config — `~/.hyperframes-vo/config.json`
```jsonc
{
  "voice": "Đức Trí",
  "engine": "vieneu",
  "whisper_model": "small",
  "default_gap_s": 0.40,
  "recent_projects": ["C:/work/greencore-v2/videos/greencore-intro-ep01"]
}
```
Voice là hằng số toàn cục cho **mọi tập** → không vào hash, không lưu trong project.

### 3.2 Project — `<ep-dir>/assets/vo/project.json` (nguồn sự thật)
```jsonc
{
  "schema_version": 1,
  "ep_dir": "greencore-intro-ep01",
  "title": "greencore-intro-ep01",
  "voice_direction": "Chuyên nghiệp, rõ ràng...",
  "lines": [
    {
      "frame": 3,
      "title": "Nỗi đau 1: Lặp lại",
      "time_range": "23.0 – 36.0s",
      "delivery": "Đánh số rõ...",
      "merged": {
        "wav": "assets/vo/03.wav",
        "duration_s": 12.4,
        "words": [ /* line-level, ghép từ fragment */ ],
        "merged_at": "2026-07-05T..."
      },
      "fragments": [
        {
          "id": "f-3-0",
          "text": "Nỗi đau thứ nhất: lặp lại.",
          "tts_text": null,
          "gap_s": null,
          "content_hash": "a1b2c3…",
          "selected_take_id": "t-2",
          "takes": [
            {
              "id": "t-1",
              "wav": "assets/vo/.takes/f-3-0/t-1.wav",
              "duration_s": 2.1,
              "words": [ /* fragment-level, start từ 0 */ ],
              "content_hash": "a1b2c3…",
              "created_at": "..."
            },
            { "id": "t-2" }
          ]
        }
      ]
    }
  ]
}
```

**Layout file trên đĩa:**
```
<ep-dir>/assets/vo/
├─ project.json
├─ .takes/<fragment-id>/<take-id>.wav   # take audio (giữ tối đa 2)
├─ 03.wav                                # line wav sau merge (output pipeline dùng)
└─ (audio_meta.json ở <ep-dir>/ — export target)
```

### 3.3 Bất biến & quy tắc dữ liệu
- **Fragment id ổn định** (`f-{frame}-{seq}`), không tái đánh số khi sửa text → take không mất
  liên kết.
- **Take giữ tối đa 2:** append take mới → nếu `len > 2` xóa take[0] + file wav. `selected_take_id`
  nếu trỏ take vừa bị xóa → trỏ take còn lại mới nhất.
- **content_hash lệch giữa fragment và take đã chọn** → badge "⚠ text đã đổi sau khi gen" (mềm,
  không auto-invalidate).
- **Atomic write** `project.json`: ghi `.tmp` rồi rename. Save sau mỗi fragment khi generate.

---

## 4. SCRIPT.md I/O

### 4.1 Import (bootstrap — mở rộng `parse_script`)
Parser đọc đủ metadata, không chỉ text:
```
## Line N — {title} (Frame N)   → frame, title
**Time:** {time_range}          → time_range
**Delivery:** {delivery}        → delivery
    {đoạn thụt 4 space}          → text (auto-split câu → fragments[])
```
Header đầu file `**Voice direction:**` → `project.voice_direction`.

Import chạy **auto-split theo câu** (regex `(?<=[.?!…;:])\s+` như `tts_chunks`) tạo fragment ban
đầu. Sau import, ranh giới do tool quản.

### 4.2 Export SCRIPT.md
Dựng lại từ `project.json`: mỗi line ghép `text` các fragment (nối bằng space) thành đoạn thụt
4 space, kèm title/time/delivery. Khớp về nội dung để git diff sạch.

### 4.3 Re-import (có chủ đích, cảnh báo)
- Nếu `project.json` đã tồn tại → endpoint re-import trả **diff preview** (line/fragment nào text
  sẽ đổi), yêu cầu xác nhận.
- Map **theo frame number**; trong line, so text từng fragment: khớp → giữ take; mới → fragment
  trống; biến mất → đánh dấu `orphan` (không xóa, ẩn khỏi UI chính, có thể khôi phục).

---

## 5. Backend API

| Method | Path | Mô tả |
|---|---|---|
| `GET` | `/api/config` | đọc global config (voice, model...) |
| `PUT` | `/api/config` | sửa config (hiếm dùng — voice bất biến) |
| `GET` | `/api/projects/recent` | danh sách project gần đây |
| `POST` | `/api/projects/open` | mở project theo `ep_dir` (load project.json) |
| `POST` | `/api/projects/import` | bootstrap từ SCRIPT.md (body: ep_dir) |
| `POST` | `/api/projects/reimport` | re-import có diff preview + confirm |
| `GET` | `/api/projects/{ep}/state` | toàn bộ project.json (UI render) |
| `PUT` | `/api/lines/{frame}/meta` | sửa title/time/delivery |
| `PUT` | `/api/fragments/{id}/text` | sửa text/tts_text/gap_s (cập nhật content_hash) |
| `POST` | `/api/fragments/{id}/split` | tách tại vị trí con trỏ → 2 fragment, **vứt take cũ** |
| `POST` | `/api/fragments/merge` | gộp 2 fragment liền kề, vứt take |
| `POST` | `/api/fragments/reorder` | (nếu cần) đổi thứ tự |
| `POST` | `/api/takes/generate` | body: `fragment_ids[]` → tạo **job** async |
| `POST` | `/api/takes/{id}/select` | chọn take dùng khi merge |
| `GET` | `/api/takes/{id}/audio` | stream wav (nghe/waveform) |
| `POST` | `/api/lines/{frame}/merge` | ghép fragment đã chọn → line wav + words[] |
| `POST` | `/api/export/audio-meta` | ghi `voices[]` vào audio_meta.json (giữ bgm/sfx) |
| `POST` | `/api/export/script` | ghi lại SCRIPT.md |
| `GET` | `/api/jobs/stream` | **SSE** — tiến độ job realtime |
| `GET` | `/api/jobs/{id}` | poll trạng thái 1 job (fallback) |

**Generate flow (async):** `POST /takes/generate` → tạo job, trả `job_id` ngay → worker infer
từng fragment (mỗi câu 1 chunk như `tts_chunks`, concat + trim), **align ngay fragment đó**, push
take vào project.json, emit SSE `progress`. UI cập nhật fragment khi nhận event.

---

## 6. Job queue (async)

TTS ~5x chậm realtime → không thể đồng bộ.

- **In-process queue** (`asyncio.Queue` + 1 worker task) — đủ cho tool local 1 người dùng.
  Serialize để không load model TTS 2 lần song song (nặng RAM).
- Model TTS + whisper **lazy-load 1 lần**, giữ trong worker (tránh reload mỗi request — vo.py phải
  `reexec_in_venv` + load mỗi lần).
- **SSE** `/api/jobs/stream` đẩy: `{job_id, fragment_id, phase: "tts"|"align"|"done", index, total}`.
- Job có thể **cancel** (bấm dừng giữa batch nhiều fragment).
- Không cần Celery/Redis — giữ zero-infra, chạy `uvicorn` là xong.

---

## 7. Vòng đời fragment (state machine)

```
      (sửa text)                    (generate → có take)
EMPTY ──────────► DRAFT ──────────────────────────► HAS_TAKE
  ▲                                                    │
  │                                          (chọn take) │
  │                                                    ▼
  │                                              SELECTED ──(merge line)──► line.merged
  │                                                    │
  └──────────── (split/merge fragment: vứt take) ◄─────┘

Badge phụ (không phải state): STALE_WARN khi fragment.content_hash ≠ selected_take.content_hash
```

**Merge line điều kiện:** mọi fragment của line phải có `selected_take_id`. Thiếu → nút Merge
disabled + chỉ rõ fragment nào trống.

---

## 8. Align theo fragment + offset

Sau khi có take (wav fragment ngắn), chạy `force_align(fragment.text, take.wav)` (port từ vo.py —
whisper chỉ cho timing, text lấy nguyên văn). Lưu `words[]` (start từ 0) trong take.

Khi **merge line**, ghép words cấp line:
```python
offset = 0.0
line_words = []
for frag in line.fragments:
    take = frag.selected_take
    gap = frag.gap_s or default_gap_s
    for w in take.words:
        line_words.append({**w, "start": w.start + offset, "end": w.end + offset})
    offset += take.duration_s + gap        # gap SAU fragment
# concat_wavs các take.wav với gap → line wav; duration_s = offset - last_gap
```
Chính xác hơn hẳn whisper đoán trên cả line dài, vì offset là do ta ghép (đã biết chắc).

---

## 9. UI flow (SPA 1 trang)

```
┌─ Topbar: [Mở/Import project ▾]  voice: Đức Trí (global)  [Export ▾: audio_meta | SCRIPT.md] ┐
├─ Left rail: danh sách Line (frame) ─┬─ Main: Line đang chọn ───────────────────────────────┐
│  ● 1  Hook            [merged ✓]    │  Line 3 — "Nỗi đau 1: Lặp lại"   [Merge line ▶]      │
│  ● 2  Câu chuyện      [3/3 ✓]       │  ┌ Fragment f-3-0 ──────────────────────────────┐    │
│  ○ 3  Nỗi đau 1  ◄    [2/3]         │  │ [text editable] "Nỗi đau thứ nhất: lặp lại." │    │
│  ○ 4  ...                           │  │ gap: 0.40  [Split] [Gen ↻] [▶ take2 ▾ ⚠]     │    │
│                                     │  │ takes:  ( )take1 2.0s  (●)take2 2.1s          │    │
│                                     │  │ ▁▂▅▇▅▂ waveform + word timing overlay          │    │
│                                     │  └───────────────────────────────────────────────┘   │
│                                     │  ┌ Fragment f-3-1  [EMPTY — cần gen] ...          ┐   │
└─────────────────────────────────────┴───────────────────────────────────────────────────┘
Bottom: [Gen tất cả fragment thiếu của line]   job progress ▓▓▓░░ 3/5 (SSE)
```

**Tương tác chính:**
- Sửa text inline → auto-save (debounce) → cập nhật content_hash → badge ⚠ nếu lệch take.
- **Split:** đặt con trỏ trong text, bấm Split → tách 2 fragment, cảnh báo "take sẽ bị xóa".
- **Merge fragment:** chọn 2 fragment liền kề → gộp, xóa take.
- **So take:** radio 2 take, bấm nghe từng bản, waveform + word overlay; chọn radio = `select`.
- **Merge line** enabled khi đủ take → ghi line wav.
- **Export** tách 2 nút rõ ràng (audio_meta / SCRIPT.md), có confirm.

---

## 10. Các cạnh khó & xử lý

| Tình huống | Xử lý |
|---|---|
| Re-import khi đã có project | Diff preview + confirm; map theo frame; fragment biến mất → orphan (không xóa) |
| Split fragment có take | Vứt take cả 2 fragment mới |
| Take thứ 3 | Xóa take cũ nhất + file wav; sửa selected nếu trỏ vào take bị xóa |
| Sửa text sau khi đã merge | line.merged giữ nguyên đến khi merge lại; badge "line cần merge lại" |
| tts_text override (đọc số) | Giữ cơ chế vo.py: `tts_text` vào TTS, `text` hiển thị caption |
| Gạch ngang `—` | Port `to_tts`: ` — `→`. `; và bỏ `—` khỏi caption words |
| Đổi voice (hiếm) | Global + bất biến: nếu thật sự đổi, mọi take thành lệch — cảnh báo toàn cục, không tự gen |
| Crash giữa batch generate | project.json save sau mỗi fragment (atomic) → không mất tiến độ |

---

## 11. Lộ trình build (milestone)

| M | Nội dung | Kết quả kiểm chứng |
|---|---|---|
| **M0** | Scaffold repo, config, `store.py`, port engine (tts/align/audio) từ vo.py, CLI smoke test | Gen + align 1 fragment qua script test, không cần UI |
| **M1** | Import SCRIPT.md → project.json; export SCRIPT.md round-trip | Import ep01, export lại, diff = rỗng |
| **M2** | API + job queue + SSE; generate/align async | curl generate → nhận SSE → take xuất hiện trong project.json |
| **M3** | UI: rail line, fragment, sửa text, gen, so 2 take, chọn take | Duyệt tay 1 line end-to-end |
| **M4** | Split/merge fragment; merge line (offset words); export audio_meta.json | audio_meta.json khớp format, chạy được captions.mjs |
| **M5** | Re-import diff + orphan; badge stale; cancel job; hoàn thiện | Sửa SCRIPT.md ngoài → re-import an toàn |

Ưu tiên: **M0–M2 là xương sống**. Có thể dừng ở M4 để dùng thực tế, M5 là polish.

---

## 12. Rủi ro cần lưu

- **Model load nặng RAM:** vieneu + whisper cùng lúc trong worker — đo trước, lazy-load whisper chỉ
  khi align.
- **Waveform lib:** WaveSurfer.js (CDN, không build step) gọn; zero-dependency thì `<audio>` +
  canvas tự vẽ.
- **Windows path:** engine port từ vo.py dùng `pathlib`. Nghe qua browser `<audio>` nên không cần
  `ffplay` như CLI — bớt phụ thuộc.
- **Đường dẫn project tuyệt đối:** tool nhận ep-dir bất kỳ → validate tồn tại `SCRIPT.md` hoặc
  `project.json`.

---

## Nguồn tham chiếu

- Logic gốc: `C:\work\greencore-v2\videos\tools\vo\vo.py` (+ `README.md`) — port engine từ đây.
- Pipeline tiêu thụ: hyperframes `audio.mjs` / `captions.mjs` / `assemble-index.mjs`.
- Ví dụ SCRIPT.md: `C:\work\greencore-v2\videos\greencore-intro-ep01\SCRIPT.md`.
