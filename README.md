# VO Studio (hyperframes-voice-management)

Web tool quản lý voiceover (voiceover) cho pipeline [hyperframes](https://github.com/heygen-com/hyperframes),
kế thừa CLI `videos/tools/vo/vo.py`. Tạo/duyệt voiceover ở cấp **fragment**, giữ lịch sử **take**,
merge thủ công thành line wav, export ra `audio_meta.json`.

Thiết kế đầy đủ: [DESIGN.md](DESIGN.md).

## Trạng thái

**M0 — xương sống engine + CLI** (đang làm). Chưa có web UI (M3+).

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
