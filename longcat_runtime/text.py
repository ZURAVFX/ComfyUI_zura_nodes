"""Split at natural boundaries before reaching LongCat's audio window."""
import re


def split_script(text, estimate_seconds, budget):
    if budget <= 0:
        raise ValueError("The reference leaves no room for generated speech.")
    remaining = text.strip()
    chunks = []
    while remaining:
        if estimate_seconds(remaining) <= budget:
            chunks.append(remaining)
            break
        lo, hi = 1, len(remaining)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if estimate_seconds(remaining[:mid]) <= budget:
                lo = mid
            else:
                hi = mid - 1
        end = lo
        sentences = list(re.finditer(r"[.!?;。！？；](?:\s+|(?=[\u4e00-\u9fff]))", remaining[:end]))
        if sentences and sentences[-1].end() >= end * 0.35:
            end = sentences[-1].end()
        else:
            spaces = list(re.finditer(r"\s+", remaining[:end]))
            if spaces:
                end = spaces[-1].end()
        chunks.append(remaining[:end].strip())
        remaining = remaining[end:].strip()
    return chunks
