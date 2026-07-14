# UI/UX research — tính năng đáng adopt cho VO Studio

Khảo sát các tool cùng họ "TTS studio có review theo đoạn" (2026-07-14), đối chiếu với UI
hiện tại (`web/app.js`), chọn ra 7 tính năng đáng adopt. Nguồn chính:

- [VibeVoice](https://github.com/vorojar/VibeVoice) — audiobook studio local, sửa/regen per-sentence.
- [Pandrator](https://github.com/lukaszliniewicz/Pandrator) — audiobook/dubbing, review playlist + mark.
- [ElevenLabs Studio](https://help.elevenlabs.io/hc/en-us/articles/30064925282577-What-is-Generation-History-in-Studio) — Generation History per-paragraph (thương mại).
- [TTS-Audio-Suite](https://github.com/diodiogod/TTS-Audio-Suite) — segment cache theo hash, chỉ regen đoạn sửa.

---

## 7 tính năng đề xuất

### Ưu tiên cao — thay đổi chất lượng review loop (→ M4.5)

**1. Nghe liên tục cả line + đánh dấu fragment lỗi khi đang nghe** *(Pandrator)*
Cách người thật duyệt voiceover: nghe cả mạch, không dừng từng câu. Play tuần tự các take
đã chọn của line (chèn im lặng theo `gap_s` ở client — nghe được nhịp gap **trước khi**
merge), phím `M` đánh dấu fragment đang phát, xong bấm "Gen đánh dấu" một lượt.
Backend không đổi: `POST /api/takes/generate` đã nhận `fragment_ids[]`.

**2. Phím tắt điều hướng** *(VibeVoice)*
`Space` nghe/dừng line, `↑↓` chuyển fragment, `←→` chuyển line, `Enter` generate fragment
đang focus, `1`/`2` chọn take, `M` đánh dấu. So 2 take là thao tác lặp nhiều nhất —
phím `1`/`2` tiết kiệm nhất.

**3. Trạng thái generate per-fragment** *(VibeVoice)*
Hiện chỉ có job bar toàn cục — không biết fragment nào đang chạy. SSE đã mang
`fragment_id` trong `fragment_start`/`fragment_done`: highlight card đang gen, disable
nút Generate của nó, badge "⏳ đang tạo".

**7. Highlight + auto-scroll fragment đang phát** *(VibeVoice)*
Khi nghe cả line: highlight card fragment đang phát, scroll theo. Word-level highlight
đã có sẵn trong take — phần này gần như miễn phí.

### Ưu tiên vừa — chi phí thấp (→ M5)

**4. A/B toggle tức thì giữa 2 take** *(ElevenLabs Generation History)*
Đã hiển thị 2 take song song; thiếu so sánh tức thì — một phím/nút phát take 1 rồi take 2
liền nhau cho cùng fragment thay vì bấm ▶ từng cái.

**5. Confirm dialog cho thao tác phá hủy** *(VibeVoice)*
Split/Gộp hiện xóa take ngay, chỉ toast sau khi xong. Fragment đã có take được chọn →
hỏi trước, vì mất take là mất công generate lại.

**6. Nút "Gen tất cả fragment stale"** *(ý tưởng segment-cache của TTS-Audio-Suite)*
Nền đã có đủ (`content_hash` + badge stale). Thiếu một nút gom quét mọi line, cạnh
"Gen fragment thiếu".

### Ghi nhận nhưng không adopt

- **Regenerate từng từ** (ElevenLabs) — cần model hỗ trợ infill; vieneu không có, fragment đã đủ nhỏ.
- **Character/emotion panel bằng LLM** (VibeVoice) — VO Studio là single-voice theo thiết kế.
- **Undo Ctrl+Z xuyên save** — textarea đã có undo native trước blur; undo xuyên store chi phí cao. Để sau M5.

---

## Kế hoạch

| Đợt | Tính năng | Phạm vi |
|---|---|---|
| **M4.5 — review ergonomics** | 1, 2, 3, 7 | thuần frontend (`web/`), không đụng backend |
| **M5** (cùng re-import/cancel job) | 4, 5, 6 | frontend + 1 endpoint gom stale nếu cần |
