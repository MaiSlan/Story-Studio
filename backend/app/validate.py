"""Quality checks for generated lines. Used while generating (to retry bad chunks) and in the
web UI (badges next to each line)."""
from __future__ import annotations

import re
import unicodedata

from .pinyin_tools import HANZI_RE, Issue, check_pinyin, hanzi_chars, traditional_diffs

LATIN_RE = re.compile(r"[A-Za-z]")


def names_from_outline(outline: dict) -> list[tuple[str, str]]:
    out = []
    for c in outline.get("characters", []) or []:
        h, p = (c.get("hanzi") or "").strip(), (c.get("primary") or "").strip()
        if h and p and len(h) >= 2:
            out.append((h, p))
    return out


def validate_line(track: str, line: dict, names: list[tuple[str, str]] | None = None) -> list[Issue]:
    issues: list[Issue] = []
    primary, hanzi, english = line.get("primary", ""), line.get("hanzi", ""), line.get("english", "")

    for field, value in (("primary", primary), ("hanzi", hanzi), ("english", english)):
        if not value.strip():
            issues.append(Issue("error", f"empty_{field}", f"The {field} text is empty."))
    if issues:
        return issues

    if not HANZI_RE.search(hanzi):
        issues.append(Issue("error", "no_hanzi", "The hanzi line contains no Chinese characters."))
    if LATIN_RE.search(hanzi):
        issues.append(Issue("warn", "latin_in_hanzi", "The hanzi line contains Latin letters."))
    trad = traditional_diffs(hanzi)
    if trad:
        pairs = ", ".join(f"{a}→{b}" for a, b in trad[:6])
        issues.append(Issue("error", "traditional", f"Traditional characters found ({pairs}). Simplified is required."))
    if len(hanzi_chars(hanzi)) > 45:
        issues.append(Issue("warn", "long_line", "This line is very long for read-aloud practice."))
    if "*" in primary + hanzi + english or "```" in primary + hanzi + english:
        issues.append(Issue("error", "markdown", "Stray markdown characters in the line."))

    if track == "pinyin":
        if HANZI_RE.search(primary):
            issues.append(Issue("error", "hanzi_in_pinyin", "The pinyin line contains Chinese characters."))
        else:
            issues.extend(check_pinyin(hanzi, primary, names))
    else:  # french
        if HANZI_RE.search(primary):
            issues.append(Issue("error", "hanzi_in_french", "The French line contains Chinese characters."))
    return issues


def validate_story(track: str, lines: list[dict], names: list[tuple[str, str]] | None = None, target: int = 0) -> dict:
    per_line: dict[int, list[dict]] = {}
    errors = warnings = 0
    prev = None
    for ln in lines:
        issues = validate_line(track, ln, names)
        key = (ln.get("primary", "").strip(), ln.get("hanzi", "").strip())
        if prev is not None and key == prev:
            issues.append(Issue("warn", "duplicate", "Same as the previous line."))
        prev = key
        if issues:
            per_line[ln["n"]] = [i.as_dict() for i in issues]
            errors += sum(i.level == "error" for i in issues)
            warnings += sum(i.level == "warn" for i in issues)
    story_notes = []
    if target and abs(len(lines) - target) > max(5, 0.2 * target):
        story_notes.append({"level": "warn", "code": "length",
                            "msg": f"The story has {len(lines)} lines; {target} were requested."})
        warnings += 1
    return {"errors": errors, "warnings": warnings, "lines": per_line, "story": story_notes}


def normalize_line(line: dict) -> dict:
    """Trim, NFC-normalise and convert any traditional characters to simplified."""
    from .pinyin_tools import to_simplified

    out = {}
    for k in ("primary", "hanzi", "english"):
        v = unicodedata.normalize("NFC", str(line.get(k, "") or "")).strip()
        v = re.sub(r"\s+", " ", v)
        out[k] = v
    out["hanzi"] = to_simplified(out["hanzi"]).replace(" ", "")
    return out
