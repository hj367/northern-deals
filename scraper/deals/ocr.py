"""Read text off specials posters (images). Many restaurants publish their weekly
specials only as a designed JPG, so we OCR it.

RapidOCR is used because it reads light-on-dark and dark-on-light panels equally
well; it tends to drop spaces between English words, which fix_spacing() repairs.
"""
from __future__ import annotations

import io
import logging
import re
from typing import Optional

log = logging.getLogger(__name__)
_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR  # heavy import, only when needed
        _engine = RapidOCR()
    return _engine


def ocr_lines(image_bytes: bytes) -> list[str]:
    """Image -> text lines in reading order (top to bottom, left to right)."""
    from PIL import Image

    im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    if im.width > 1400:  # big posters slow OCR down without helping accuracy
        im = im.resize((1400, int(im.height * 1400 / im.width)))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    result, _ = _get_engine()(buf.getvalue())
    if not result:
        return []
    boxes = [(b[0][1], b[0][0], b[2][1] - b[0][1], t) for b, t, conf in result if float(conf) >= 0.5]
    boxes.sort()
    # merge fragments that sit on the same row
    lines: list[list] = []
    for y, x, h, t in boxes:
        if lines and abs(lines[-1][0] - y) < max(8, h * 0.5):
            lines[-1][1].append((x, t))
        else:
            lines.append([y, [(x, t)]])
    return [fix_spacing(" ".join(t for _, t in sorted(parts))) for _, parts in lines]


_KEEP_WHOLE = {
    "eisbein", "schnitzel", "calamari", "espetada", "boerewors", "bobotie", "biltong", "droewors",
    "carpaccio", "tiramisu", "margherita", "quesadilla", "chimichanga", "prego", "trinchado",
    "potjie", "bunny", "chakalaka", "poutine", "brisket", "focaccia", "sirloin", "ribeye", "takeaway",
}


def fix_spacing(s: str) -> str:
    try:
        import wordninja
    except ImportError:  # pragma: no cover
        wordninja = None
    # OCR reads 0 as O inside prices: R3O -> R30; "R30Off" read as "R3OOff"
    s = re.sub(r"\bR(\d)[Oo](?=[Oo]ff)", r"R\g<1>0 ", s)
    s = re.sub(r"\bR(\d*)[Oo](\d*)\b", lambda m: f"R{m.group(1)}0{m.group(2)}", s)
    s = re.sub(r"\s*([+&/|])\s*", r" \1 ", s)
    s = re.sub(r"(\d+(?:g|kg|ml|l))(?=[A-Z])", r"\1 ", s)          # 400gRibs -> 400g Ribs
    s = re.sub(r"([a-z'])([A-Z])", r"\1 \2", s)                     # AllKids -> All Kids
    s = re.sub(r"([a-z])(R\d)", r"\1 \2", s)                        # SideR115 -> Side R115
    s = re.sub(r"(\d)(pm|am)\b", r"\1 \2", s, flags=re.I)
    s = re.sub(r"(?<![R\d])([a-z]{2,})(\d)", r"\1 \2", s)          # From4 -> From 4
    out = []
    for tok in s.split():
        tok = tok.replace("'", "\u2019") if re.fullmatch(r"[A-Za-z]+'[a-z]+[A-Za-z]*", tok) else tok
        if "\u2019" in tok:  # kiddie'smeal -> kiddie's meal
            head, _, tail = tok.partition("\u2019")
            tok = head + "'" + (tail[:1] + " " + fix_spacing(tail[1:]) if len(tail) > 3 else tail)
        alpha = re.fullmatch(r"[A-Za-z]+", tok)
        if wordninja and alpha and len(tok) >= 7 and tok.lower() not in _KEEP_WHOLE:
            parts = wordninja.split(tok)
            if len(parts) > 1 and all(len(p) >= 2 for p in parts):
                i, rebuilt = 0, []
                for p in parts:
                    rebuilt.append(tok[i:i + len(p)])
                    i += len(p)
                tok = " ".join(rebuilt)
        out.append(tok)
    return re.sub(r"\s+", " ", " ".join(out)).strip()


DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_DAY_RE = re.compile(r"^\W*(" + "|".join(DAYS) + r")s?\b[\s:–-]*(.*)$", re.I)
_DEAL_RE = re.compile(r"R\s?\d{2,4}|half[- ]price|\d+\s*%\s*off|R\d+\s*off|free|2\s*for\s*1|two for one|buy one", re.I)
_NOTE_RE = re.compile(r"^\W*\*+|^t\s*&\s*cs|valid for|selected", re.I)


def parse_weekly_specials(lines: list[str]) -> tuple[list[dict], Optional[str]]:
    """Lines of a weekly specials poster/page -> [{"day","text","price","note"}], footer note."""
    out: list[dict] = []
    day: Optional[str] = None
    footer: list[str] = []
    for raw in lines:
        line = raw.strip(" *").strip()
        if not line:
            continue
        m = _DAY_RE.match(line)
        if m:
            day = m.group(1).capitalize()
            line = m.group(2).strip()
            if not line:
                continue
        if re.search(r"\bfrom \d|sit[- ]down|takeaway|no sharing", line, re.I) and not re.search(r"R\s?\d", line):
            footer.append(line)
            continue
        strong_deal = re.search(r"half[- ]price|free|\d+\s*%\s*off|R\s?\d{2,4}", line, re.I)
        if day and _NOTE_RE.search(raw) and not strong_deal and out and out[-1]["day"] == day:
            out[-1]["note"] = (out[-1].get("note", "") + " " + line).strip()
            continue
        if day and _DEAL_RE.search(line):
            price = re.search(r"R\s?(\d{2,4})(?![\d.]*\s*off)", line, re.I)
            out.append({"day": day, "text": line, "price": float(price.group(1)) if price else None})
    return out, (" | ".join(footer) or None)
