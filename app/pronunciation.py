"""Bảng phiên âm ghi đè cho tên chất (và thuật ngữ) đọc bằng tiếng Anh.

Bộ phiên âm của vieneu (sea-g2p, dùng espeak en-us cho từ tiếng Anh) đọc đúng phần lớn tên chất
IUPAC, nhưng sai ở một số từ (trọng âm đặt sai chỗ, chen thêm nguyên âm, tên riêng tiếng Pháp).
Module này giữ bảng sửa: từ (chữ thường) -> phiên âm cùng bộ ký hiệu với G2P (IPA kiểu espeak:
ɹ cho r, oʊ, ɑː, ˈ trọng âm chính, ˌ phụ).

Mỗi bài có thể thêm/ghi đè bằng `pronunciations.json` cạnh `SCRIPT.md`:
    {"chatelier": "ʃɑːtəljˈeɪ"}

`signature(text, lex)` là dấu vân tay của các mục bảng LIÊN QUAN tới một đoạn văn bản; lưu vào
Take.pron để biết take nào sinh trước khi bảng đổi (chỉ take có từ liên quan mới bị coi là lỗi thời).
Module thuần Python, không phụ thuộc engine.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

# Chỉ ghi các từ mà phiên âm mặc định SAI so với cách đọc chuẩn (tiếng Anh Mỹ).
BUILTIN: dict[str, str] = {
    "dinitrogen": "daɪnˈaɪtɹədʒən",         # /daɪˈnaɪtrədʒən/ (mặc định nhấn vào "đi")
    "hypochlorous": "hˌaɪpəklˈɔːɹəs",        # /ˌhaɪpəˈklɔːrəs/ (mặc định chen thêm nguyên âm)
    "iodine": "ˈaɪədˌaɪn",                   # /ˈaɪədaɪn/ (mặc định đọc "ai-ơ-đin")
    "monoxide": "mənˈɑːksaɪd",               # /məˈnɑːksaɪd/ (mặc định đọc "mun-ốc-xai")
    "phenolphthalein": "fˌiːnɑːlfθˈæliːn",    # /ˌfiːnɑːlfˈθæliːn/ (mặc định nhấn sai chỗ)
    "enthalpy": "ˈɛnθælpi",                  # /ˈɛnθælpi/ (mặc định nhấn âm thứ hai)
    "chatelier": "ʃɑːtəljˈeɪ",               # /ʃɑːtəlˈjeɪ/ (tên Pháp; mặc định đọc "chéi-tờ-li-ờ")
}

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def load(ep: Path) -> dict[str, str]:
    """Bảng dựng sẵn + `pronunciations.json` của bài (nếu có, ghi đè). Lỗi cú pháp -> ValueError."""
    lex = dict(BUILTIN)
    path = Path(ep) / "pronunciations.json"
    if path.exists():
        try:
            extra = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: JSON không hợp lệ: {exc}") from exc
        if not isinstance(extra, dict):
            raise ValueError(f"{path}: phải là object {{từ: phiên âm}}")
        for word, ipa in extra.items():
            if not isinstance(word, str) or not isinstance(ipa, str) or not ipa.strip():
                raise ValueError(f"{path}: mục {word!r} cần phiên âm là chuỗi không rỗng")
            lex[word.lower()] = ipa.strip()
    return lex


def relevant(text: str, lex: dict[str, str] | None) -> dict[str, str]:
    """Các mục của bảng có từ xuất hiện trong `text`."""
    if not lex:
        return {}
    words = {w.lower() for w in _WORD.findall(text)}
    return {w: lex[w] for w in sorted(words & lex.keys())}


def signature(text: str, lex: dict[str, str] | None) -> str:
    """Dấu vân tay các mục liên quan tới `text`; "" nếu không mục nào."""
    rel = relevant(text, lex)
    if not rel:
        return ""
    blob = json.dumps(rel, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:10]


def swap_tokens(phonemes: str, mapping: dict[str, str]) -> str:
    """Thay token âm vị trong chuỗi phiên âm: `mapping` = {phiên âm mặc định: phiên âm chuẩn}.
    Từ tiếng Anh là MỘT token (từ tiếng Việt tách theo âm tiết) nên so khớp nguyên token là an toàn;
    dấu câu dính đuôi token được giữ nguyên."""
    toks = phonemes.split(" ")
    for i, tok in enumerate(toks):
        core = tok.rstrip(".,!?;:")
        if core in mapping:
            toks[i] = mapping[core] + tok[len(core):]
    return " ".join(toks)
