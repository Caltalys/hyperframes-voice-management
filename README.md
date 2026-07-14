# VO Studio (hyperframes-voice-management)

Web tool quản lý voiceover (voiceover) cho pipeline [hyperframes](https://github.com/heygen-com/hyperframes),
kế thừa CLI `videos/tools/vo/vo.py`. Tạo/duyệt voiceover ở cấp **fragment**, giữ lịch sử **take**,
merge thủ công thành line wav, export ra `audio_meta.json`.

Thiết kế đầy đủ: [DESIGN.md](DESIGN.md).

## Trạng thái

- **M0** — xương sống engine + CLI. ✓
- **M2** — FastAPI + job queue async + SSE (generate/align async). ✓
- **M3** — web UI: rail line, fragment, sửa text/gap, generate (SSE), so 2 take + waveform, chọn take, merge line, export. ✓
- **M4** — split/merge fragment (vứt take, xóa line.merged). ✓
- **M4.5** — review ergonomics: nghe cả line (gap client-side), đánh dấu fragment khi nghe
  → gen lại một lượt, phím tắt, trạng thái generate per-fragment. Xem [UIUX.md](UIUX.md). ✓
- **M5** — re-import diff/orphan, cancel job, A/B toggle take, confirm split/gộp, gen stale. (chưa)

## Cài đặt

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      |  *nix: source .venv/bin/activate
pip install -e .                 # lõi (numpy + pydantic) — đủ chạy smoke offline
pip install -e ".[engine]"       # thêm TTS + align thật (vieneu, faster-whisper) — nặng
```

## Kiểm chứng M0

```bash
# Smoke offline: parser -> gen (fake TTS) -> align (fake) -> merge -> export
# Không cần tải model, xác minh toàn bộ đường ống dữ liệu.
python -m app.cli smoke

# Smoke đầy đủ (cần .[engine]): dùng vieneu + faster-whisper thật.
python -m app.cli smoke --full
```

## Chạy web backend (M2)

```bash
pip install -e ".[web]"
# engine thật (mặc định): cần .[engine]. Test không cần model: đặt VO_STUDIO_ENGINE=fake
uvicorn app.main:app --reload           # http://127.0.0.1:8000  (/docs cho OpenAPI)

# Kiểm chứng API end-to-end (server chạy với VO_STUDIO_ENGINE=fake):
python scripts/api_smoke.py
```

Luồng async: `POST /api/takes/generate` trả `job_id` ngay; worker sinh take trong
thread, đẩy tiến độ qua SSE `GET /api/jobs/stream`; poll `GET /api/jobs/{id}` để biết
`done`. Xem toàn bộ endpoint ở `/docs`.

## CLI (M0)

```bash
python -m app.cli import <ep-dir>              # SCRIPT.md -> project.json
python -m app.cli gen    <ep-dir> --frame N    # sinh take cho fragment của line N (TTS thật)
python -m app.cli merge  <ep-dir> --frame N    # ghép take đã chọn -> line wav + words
python -m app.cli export <ep-dir>              # ghi voices[] vào audio_meta.json
python -m app.cli script <ep-dir>              # export lại SCRIPT.md từ project.json
```

`<ep-dir>` là thư mục tập bất kỳ có `SCRIPT.md` (vd. một thư mục trong `videos/` của greencore-v2).
Tool ghi trạng thái vào `<ep-dir>/assets/vo/` và output vào `<ep-dir>/audio_meta.json`.

## Cấu trúc

Xem [DESIGN.md](DESIGN.md) mục 2. Lõi có thể tái dùng cho web (M2+):
`app/pipeline.py` (generate_take, merge_line, export_audio_meta) — API sẽ gọi thẳng các hàm này.
