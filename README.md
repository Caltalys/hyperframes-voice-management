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
- **M5** — re-import diff preview + orphan/khôi phục, cancel job, A/B toggle take,
  confirm split/gộp, gen stale toàn project. ✓

## Cài đặt

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      |  *nix: source .venv/bin/activate
pip install -e .                 # lõi (numpy + pydantic) — đủ chạy smoke offline
pip install -e ".[engine]"       # thêm TTS + align thật (vieneu, faster-whisper) — nặng
```

## Cấu hình (voice / engine)

Config toàn cục ở `~/.hyperframes-vo/config.json` (mẫu: [config.default.json](config.default.json)); `voice` là hằng số dùng cho MỌI tập.

- `voice` **phải là preset của engine đang chọn**. Với vieneu, liệt kê preset hợp lệ: `python -c "from vieneu import Vieneu; print(Vieneu().list_preset_voices())"` (vd. `Minh Đức`, `Phạm Tuyên`, `Trúc Ly`...). Voice không tồn tại -> generate báo `ValueError: Voice '...' not found`.
- `engine` chọn backend TTS đã đăng ký (mặc định `vieneu`). Env `VO_STUDIO_ENGINE` override (`fake` = sine wav offline, không tải model).

**Đổi thư viện TTS**: backend đăng ký qua registry ở `app/engine/tts.py`. Thêm thư viện mới = viết 1 lớp `TTSEngine.generate(...)` + `@register_tts("tên")`, rồi đặt `"engine": "tên"` trong config — không sửa `pipeline`/`jobs`/`cli`.

## Lưu ý khi chạy engine thật

Gặp khi chạy `build`/`gen` với `vieneu==3.8.3` + `faster-whisper` lần đầu (Linux, ONNX Runtime 1.29.0):

- **`External data path escapes model directory`** (ONNXRuntimeError, mọi fragment đều lỗi). ONNX Runtime
  từ chối đọc file dữ liệu ngoài khi đường dẫn thật (sau symlink) nằm ngoài thư mục model, mà cache
  Hugging Face lưu file model bằng symlink trỏ vào `blobs/`. Cách xử lý: thay symlink trong `snapshots/` bằng
  bản sao thật, rồi chạy với `HF_HUB_OFFLINE=1` (nếu để online, `huggingface_hub` kiểm tra lại và tạo lại symlink).
  Tải trước model whisper trước khi chuyển sang offline:

  ```bash
  python - <<'EOF'
  import shutil
  from pathlib import Path
  from faster_whisper.utils import download_model
  download_model("small")                      # whisper_model trong config
  for f in (Path.home() / ".cache/huggingface/hub").glob("models--*/snapshots/*/**/*"):
      if f.is_symlink():
          target = f.resolve(); f.unlink(); shutil.copy2(target, f)
  EOF
  HF_HUB_OFFLINE=1 python -m app.cli build <ep-dir>
  ```

  Cần chạy sau khi vieneu đã tải model (lần chạy `build` đầu tiên sẽ lỗi như trên nhưng đã kéo model về cache).
  Chưa kiểm chứng trên Windows, nơi `huggingface_hub` thường dùng bản sao thay vì symlink.
- **`open() got an unexpected keyword argument 'metadata_errors'`** (lúc align). PyAV 19.0.2 bỏ tham số
  `metadata_errors` mà faster-whisper 1.2.1 vẫn truyền. `pyproject.toml` đã chặn `av<19` (PyAV 15.1 đến 18.1
  đều chạy được); nếu môi trường đã cài PyAV 19, chạy `pip install "av<19"`.
- **Môi trường chặn mạng:** lần đầu cần truy cập `huggingface.co` và `*.hf.co` (file model đi qua
  `cas-server.xethub.hf.co` và `us.aws.cdn.hf.co`).

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
python -m app.cli build  <ep-dir> [--dry-run]  # SCRIPT.md -> audio_meta.json trọn bài, không cần duyệt tay
python -m app.cli import <ep-dir>              # SCRIPT.md -> project.json
python -m app.cli gen    <ep-dir> --frame N    # sinh take cho fragment của line N (TTS thật)
python -m app.cli merge  <ep-dir> --frame N    # ghép take đã chọn -> line wav + words
python -m app.cli export <ep-dir>              # ghi voices[] vào audio_meta.json
python -m app.cli script <ep-dir>              # export lại SCRIPT.md từ project.json
```

`<ep-dir>` là thư mục tập bất kỳ có `SCRIPT.md` (vd. một thư mục trong `videos/` của greencore-v2).
Tool ghi trạng thái vào `<ep-dir>/assets/vo/` và output vào `<ep-dir>/audio_meta.json`.

### `build` — dùng từ hệ thống khác

Hệ thống tạo video khác gọi `vo-studio build <ep-dir>` (subprocess) rồi đọc `audio_meta.json`;
hai bên chỉ chung hợp đồng file. Engine lấy từ config / env `VO_STUDIO_ENGINE`. Mỗi lần chạy:

1. Parse `SCRIPT.md` **strict**: lỗi cú pháp -> in từng dòng sai, exit 2, chưa đụng gì.
2. Có `project.json` thì re-import (fragment không đổi giữ nguyên take); chưa có thì tạo mới.
3. Sinh take cho fragment chưa có take được chọn, hoặc take đã stale (text/tts/gap đổi, hoặc
   sinh bằng voice khác voice hiện tại). **Không ghi đè** take đã chọn mà không stale.
4. Merge lại line có fragment vừa sinh, rồi ghi `audio_meta.json`.

`--dry-run` chỉ liệt kê fragment sẽ sinh, không ghi gì xuống đĩa. Chạy lại khi không đổi gì thì không sinh gì. Một fragment lỗi không dừng build: build chạy tiếp,
liệt kê lỗi cuối và exit 1; line chưa merge được không lọt vào `audio_meta.json`. Phiên bản
thư viện TTS khác phiên bản đã sinh take chỉ cảnh báo, không sinh lại. Build in tỷ lệ từ
`matched=false`.

Định dạng `SCRIPT.md` (chế độ strict của `build`; web/`import` vẫn bỏ qua lặng lẽ dòng lạ):

- Trước `## Line` đầu tiên chỉ có: dòng trống, `# tiêu đề`, `---`, `**Voice direction:**`.
- Mỗi line: `## Line N` (phần sau N là tiêu đề, `(Frame M)` tùy chọn). Số N là khóa của line.
- Trong line: `**Time:**`, `**Delivery:**`, `**Pause after:** 0.8s`, `---`, dòng trống, và lời giảng
  **thụt đúng 4 khoảng trắng**. Dòng khác (kể cả `**Key:**` lạ) là lỗi.

**Cue** `{{cue:id}}` trong lời giảng (id `[a-z0-9-]+`, duy nhất trong bài, phải có từ ngay sau): bị bỏ khỏi
text/`tts_text` trước khi tách câu và đọc TTS, không nằm trong hash (dời cue hay đổi id không sinh lại audio).
Build phân giải cue trên `words[]` của cả line (cue đứng ở biên hai câu vẫn đúng) và ghi
`voices[].cues = [{id, word_index, word_id, time_s, matched}]`, `time_s` tính từ đầu line. Lỗi: trùng id,
cue cuối line, id sai dạng. Cảnh báo: cue neo vào từ `matched=false`.

Trường mới trong `audio_meta.json`: `words[].matched` (`false` = timestamp nội suy, không phải
từ nhận dạng) và `voices[].pause_after_s` (chỉ có khi script khai báo `**Pause after:**`). Mỗi take
trong `project.json` ghi `voice` và `engine_version` lúc sinh. File cũ thiếu các trường này vẫn đọc được.

Kiểm chứng offline: `python scripts/build_check.py` và `python scripts/matched_check.py`.

## Cấu trúc

Xem [DESIGN.md](DESIGN.md) mục 2. Lõi có thể tái dùng cho web (M2+):
`app/pipeline.py` (generate_take, merge_line, export_audio_meta) — API sẽ gọi thẳng các hàm này.
