"""Gắn bảng phiên âm (app/pronunciation.py) vào bộ phiên âm của vieneu.

G2P của vieneu 3.8.3 nhận `phoneme_dict` nhưng BỎ QUA nó, nên ghi đè ở mức chuỗi âm vị: lấy phiên âm
mặc định của từng từ trong bảng rồi thay đúng token đó trong kết quả. Cùng giọng, cùng nhịp câu,
không phải cắt-ghép âm thanh. Cài một lần; bảng đang dùng đổi bằng `set_active`.
"""

from __future__ import annotations

from .. import pronunciation

_active: dict[str, str] = {}
_installed = False
_default_cache: dict[str, str] = {}


def set_active(lex: dict[str, str] | None) -> None:
    global _active
    _active = dict(lex or {})


def install() -> None:
    """Idempotent. Phải gọi sau khi vieneu đã import được (cần vieneu_utils)."""
    global _installed
    if _installed:
        return
    import vieneu_utils.phonemize_text as P

    original = P.phonemize_text_with_emotions

    def default_of(word: str) -> str:
        if word not in _default_cache:
            _default_cache[word] = original(word).strip().rstrip(".,!?;:")
        return _default_cache[word]

    def patched(text: str) -> str:
        out = original(text)
        if not _active:
            return out
        mapping = {default_of(w): ipa for w, ipa in _active.items()}
        return pronunciation.swap_tokens(out, mapping)

    P.phonemize_text_with_emotions = patched
    try:  # module v3turbo import tên hàm lúc nạp nên cũng phải thay
        import vieneu.v3turbo as V
        V.phonemize_text_with_emotions = patched
    except ImportError:
        pass
    _installed = True
