"""Find the same product at different stores (for cross-store comparison)."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from rapidfuzz import fuzz

from .models import ProductObs, norm_text

_UNIT = {"g": 1, "gr": 1, "kg": 1000, "ml": 1, "l": 1000, "lt": 1000, "litre": 1000, "liter": 1000}
_SIZE_RE = re.compile(r"(?:(\d+)\s*[x×]\s*)?(\d+(?:[.,]\d+)?)\s*(kg|g|gr|ml|l|lt|litre|liter)\b", re.I)
_COUNT_RE = re.compile(r"\b(\d+)\s*(?:'s|s\b|pack|pk|tablets|capsules|sheets|rolls|bags|pods)\b", re.I)
STOP = {"the", "and", "with", "for", "pack", "each", "ea", "x", "of", "in", "a"}


def size_key(name: str, size_text: Optional[str] = None) -> Optional[str]:
    """'Nescafe Gold 200g' -> 'w200', 'Milk 6 x 1L' -> 'w6000', 'Panado 24s' -> 'c24'."""
    s = f"{name} {size_text or ''}"
    m = _SIZE_RE.search(s)
    if m:
        packs = int(m.group(1) or 1)
        qty = float(m.group(2).replace(",", "."))
        unit = m.group(3).lower()
        return f"w{round(packs * qty * _UNIT[unit])}"
    m = _COUNT_RE.search(s)
    if m:
        return f"c{int(m.group(1))}"
    return None


def name_tokens(name: str) -> str:
    t = _SIZE_RE.sub(" ", name)
    t = norm_text(t)
    return " ".join(w for w in t.split() if w not in STOP and not w.isdigit())


def group_same_products(items: list[ProductObs], threshold: int = 88) -> list[list[ProductObs]]:
    """Groups of observations that are the same product at different stores."""
    groups: list[list[ProductObs]] = []
    by_barcode: dict[str, list[ProductObs]] = defaultdict(list)
    rest: list[ProductObs] = []
    for p in items:
        if p.barcode and len(p.barcode) >= 8:
            by_barcode[p.barcode.lstrip("0")].append(p)
        else:
            rest.append(p)
    for g in by_barcode.values():
        groups.append(g)

    # Block by size so we only fuzzy-compare like with like.
    blocks: dict[str, list[tuple[str, ProductObs]]] = defaultdict(list)
    for p in rest:
        sk = size_key(p.name, p.size_text)
        if sk:
            blocks[sk].append((name_tokens(p.name), p))
    # Products with barcodes can still match barcode-less ones at other stores.
    for g in by_barcode.values():
        sk = size_key(g[0].name, g[0].size_text)
        if sk:
            blocks[sk].append((name_tokens(g[0].name), g[0]))

    used: set[int] = set()
    for sk, members in blocks.items():
        for i, (ti, pi) in enumerate(members):
            if id(pi) in used:
                continue
            group = [pi]
            for tj, pj in members[i + 1:]:
                if id(pj) in used or pj.store == pi.store or any(x.store == pj.store for x in group):
                    continue
                if (fuzz.token_set_ratio(ti, tj) >= threshold and fuzz.token_sort_ratio(ti, tj) >= 80
                        and _brand_ok(ti, tj) and _variant_ok(ti, tj)):
                    group.append(pj)
                    used.add(id(pj))
            if len(group) > 1:
                used.add(id(pi))
                # merge into an existing barcode group if pi came from one
                bc = next((g for g in by_barcode.values() if g[0] is pi), None)
                if bc is not None:
                    bc.extend(x for x in group[1:])
                else:
                    groups.append(group)
    return [g for g in groups if len({p.store for p in g}) > 1]


VARIANT_WORDS = {"refill", "refills", "pouch", "jar", "tin", "sachet", "sachets", "gold", "mild", "decaf",
                 "light", "lite", "zero", "sugar", "free", "kids", "baby", "mini", "max", "extra", "original"}


def _variant_ok(a: str, b: str) -> bool:
    """'Coffee Refill Pack' is not 'Coffee' in a jar; 'Gold Mild' is not the regular one."""
    return (set(a.split()) & VARIANT_WORDS) == (set(b.split()) & VARIANT_WORDS)


def _brand_ok(a: str, b: str) -> bool:
    """First word is usually the brand; 'PnP milk' must not match 'Clover milk'."""
    wa, wb = a.split()[:1], b.split()[:1]
    return wa == wb
