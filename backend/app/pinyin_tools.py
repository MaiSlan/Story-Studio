"""Pinyin helpers: build pinyin from hanzi, and check a pinyin line against its hanzi.

The AI writes both the hanzi and the pinyin. This module is the safety net: it uses the
`pypinyin` dictionary to check that the pinyin really matches the characters, syllable by
syllable, and can rebuild a line's pinyin from the hanzi when the AI got it wrong.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from pypinyin import Style, pinyin as _pinyin

try:  # optional: better word grouping for rebuilt pinyin (pip install jieba)
    import jieba  # type: ignore

    jieba.setLogLevel(60)
except Exception:  # pragma: no cover
    jieba = None

try:  # optional: detect/convert traditional characters (pip install opencc-python-reimplemented)
    from opencc import OpenCC

    _T2S = OpenCC("t2s")
except Exception:  # pragma: no cover
    _T2S = None

HANZI_RE = re.compile(r"[一-鿿]")
_TONE_MARKS = {"̄": 1, "́": 2, "̌": 3, "̀": 4}

PUNCT_MAP = {
    "，": ",", "、": ",", "。": ".", "！": "!", "？": "?", "：": ":", "；": ";",
    "（": "(", "）": ")", "…": "…", "—": "—", "《": "", "》": "", "「": "“", "」": "”",
}


@dataclass
class Issue:
    level: str  # "error" | "warn"
    code: str
    msg: str

    def as_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "msg": self.msg}


# ----------------------------------------------------------------- small utilities
def hanzi_chars(text: str) -> list[str]:
    return [c for c in text if HANZI_RE.match(c)]


def to_simplified(text: str) -> str:
    return _T2S.convert(text) if _T2S else text


def traditional_diffs(text: str) -> list[tuple[str, str]]:
    """[(traditional_char, simplified_char), ...] for characters OpenCC would change."""
    if not _T2S:
        return []
    out = []
    for ch in text:
        if HANZI_RE.match(ch):
            s = _T2S.convert(ch)
            if s != ch:
                out.append((ch, s))
    return out


def toneless(s: str) -> str:
    """Remove tone marks but keep ü. 'Nǚ' -> 'nü'."""
    nfd = unicodedata.normalize("NFD", s.lower())
    return unicodedata.normalize("NFC", "".join(c for c in nfd if c not in _TONE_MARKS))


def tone_of(syllable: str) -> int:
    """1-4, or 0 for neutral/unmarked."""
    for c in unicodedata.normalize("NFD", syllable):
        if c in _TONE_MARKS:
            return _TONE_MARKS[c]
    return 0


def letters_only(s: str) -> str:
    """Pinyin reduced to its letters: spaces, apostrophes, hyphens, punctuation removed; v -> ü."""
    s = unicodedata.normalize("NFC", s.lower()).replace("v", "ü")
    return "".join(c for c in s if c.isalpha())


# ----------------------------------------------------------------- reading from hanzi
def _readings(hanzi: str) -> list[str]:
    """One tone-marked syllable per Chinese character of `hanzi` (context-aware)."""
    res = _pinyin(hanzi, style=Style.TONE, errors="ignore", strict=False)
    return [r[0] for r in res]


def _all_readings(ch: str) -> list[str]:
    res = _pinyin(ch, style=Style.TONE, heteronym=True, errors="ignore", strict=False)
    return res[0] if res else []


def pinyin_from_hanzi(hanzi: str, names: list[tuple[str, str]] | None = None) -> str:
    """Rebuild a pinyin line from hanzi.

    `names` is [(hanzi_name, spelled_pinyin)] from the story's character list so names keep
    their agreed spelling and capitals. Words are grouped with jieba if installed; otherwise
    every syllable is separated by a space.
    """
    names = sorted(names or [], key=lambda t: -len(t[0]))
    syl = _readings(hanzi)
    chars = hanzi_chars(hanzi)
    if len(syl) != len(chars):  # unknown characters: fall back to per-char best effort
        syl = [(_pinyin(c, style=Style.TONE, errors="ignore") or [[c]])[0][0] for c in chars]

    # map char index in `hanzi` -> syllable
    syl_at: dict[int, str] = {}
    k = 0
    for i, ch in enumerate(hanzi):
        if HANZI_RE.match(ch):
            syl_at[i] = syl[k]
            k += 1

    # textbook tone changes for 不 and 一 (third-tone sandhi is deliberately NOT written)
    for i, ch in enumerate(hanzi):
        if ch not in "不一" or i not in syl_at or i + 1 not in syl_at:
            continue
        nxt = tone_of(syl_at[i + 1])
        if ch == "不" and nxt == 4:
            syl_at[i] = "bú"
        elif ch == "一" and not (i > 0 and hanzi[i - 1] in "第十二三四五六七八九零万"):
            if nxt == 4:
                syl_at[i] = "yí"
            elif nxt in (1, 2, 3):
                syl_at[i] = "yì"

    # mark name spans
    name_at: dict[int, tuple[int, str]] = {}
    for h, spelled in names:
        start = 0
        while (idx := hanzi.find(h, start)) != -1:
            if not any(j in name_at for j in range(idx, idx + len(h))):
                name_at[idx] = (len(h), spelled)
            start = idx + len(h)

    # word segmentation over the hanzi string
    words = list(jieba.cut(hanzi)) if jieba else [c for c in hanzi]
    out: list[str] = []
    pos = 0
    skip_until = -1
    for w in words:
        wstart = pos
        pos += len(w)
        if wstart < skip_until:
            continue
        piece_syl: list[str] = []
        j = wstart
        while j < wstart + len(w):
            if j in name_at:
                ln, spelled = name_at[j]
                piece_syl.append(("§" + spelled))
                j += ln
                skip_until = max(skip_until, j)
            elif j in syl_at:
                piece_syl.append(syl_at[j])
                j += 1
            else:
                piece_syl.append("¶" + PUNCT_MAP.get(hanzi[j], hanzi[j]))
                j += 1
        out.append(piece_syl)  # type: ignore[arg-type]

    # join: syllables inside a word glued, words separated by a space, punctuation attached
    text = ""
    for word in out:
        cell = ""
        for s in word:
            if s.startswith("¶"):
                cell += s[1:]
            elif s.startswith("§"):
                cell += s[1:]
            else:
                cell += s
        is_punct = all(s.startswith("¶") for s in word)
        if not text or is_punct and cell in {",", ".", "!", "?", ":", ";", ")", "”", "…"}:
            text += cell
        elif text.endswith(("“", "(")):
            text += cell
        else:
            text += " " + cell
    text = text.strip()
    if text:
        # capitalise the first letter of the line, after sentence ends, and after an opening quote
        lower = "a-zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜü"
        text = re.sub(rf"^(“?)([{lower}])", lambda m: m.group(1) + m.group(2).upper(), text)
        text = re.sub(rf"([.!?]\s+“?|:\s+“)([{lower}])", lambda m: m.group(1) + m.group(2).upper(), text)
    return unicodedata.normalize("NFC", text)


# ----------------------------------------------------------------- checking
def check_pinyin(hanzi: str, pinyin_text: str, names: list[tuple[str, str]] | None = None) -> list[Issue]:
    """Compare a pinyin line with its hanzi, syllable by syllable."""
    issues: list[Issue] = []
    chars = hanzi_chars(hanzi)
    if not chars:
        return issues

    if re.search(r"[A-Za-züÜ]+[1-5]\b", pinyin_text):
        issues.append(Issue("error", "tone_numbers", "Pinyin uses tone numbers; tone marks (ā á ǎ à) are required."))

    expected = _readings(hanzi)
    if len(expected) != len(chars):
        issues.append(Issue("warn", "unchecked", "Some characters are unknown to the checker; this line was not fully verified."))
        return issues

    actual = letters_only(pinyin_text)
    names = sorted(names or [], key=lambda t: -len(t[0]))
    name_at: dict[int, tuple[int, str]] = {}  # index in `chars`
    joined = "".join(chars)
    for h, spelled in names:
        s = 0
        while (idx := joined.find(h, s)) != -1:
            if not any(j in name_at for j in range(idx, idx + len(h))):
                name_at[idx] = (len(h), spelled)
            s = idx + len(h)

    p = 0
    i = 0
    while i < len(chars):
        ch = chars[i]
        # ---- character names: compare the whole name as spelled in the outline
        if i in name_at:
            ln, spelled = name_at[i]
            want = letters_only(spelled)
            got = actual[p : p + len(want)]
            if got != want:
                issues.append(Issue("warn", "name_spelling",
                                    f"Name “{joined[i:i+ln]}” should be spelled “{spelled}” (found “{pinyin_text}” here)."))
                # try to resynchronise on toneless letters
                if toneless(got) != toneless(want):
                    return issues
            p += len(want)
            i += ln
            continue

        exp = expected[i]
        exp_nt = toneless(exp)

        # ---- erhua
        if ch == "儿" and exp_nt == "er":
            if actual[p : p + 2] == "er":
                p += 2
            elif actual[p : p + 1] == "r":
                p += 1
            else:
                issues.append(Issue("error", "syllable_mismatch", "Pinyin does not match the hanzi around “儿”."))
                return issues
            i += 1
            continue

        # candidate readings: expected first, then other known readings of the character
        cands = [exp] + [r for r in _all_readings(ch) if r != exp]
        matched = None
        for cand in cands:
            cnt = toneless(cand)
            if toneless(actual[p : p + len(cnt)]) == cnt:
                matched = cand
                break
        if matched is None:
            near = actual[p : p + 8]
            issues.append(Issue(
                "error", "syllable_mismatch",
                f"Hanzi “{ch}” (character {i + 1}) should read “{exp}” but the pinyin continues “{near}”. "
                "A syllable is probably missing, extra or wrong."))
            return issues

        act_syl = actual[p : p + len(toneless(matched))]
        # NB: `actual` kept tone marks (letters_only does not strip them)
        nxt_tone = tone_of(expected[i + 1]) if i + 1 < len(expected) else None
        ta, te = tone_of(act_syl), tone_of(matched)
        if matched != exp and te != 0:  # neutral-tone alternates are grammatical particles (地 de, 得 de)
            issues.append(Issue("warn", "reading", f"“{ch}” is read “{matched}” here; the dictionary default is “{exp}”. Check this polyphonic character."))
        if ta != te:
            sandhi_ok = (
                (ch == "不" and te == 4 and ta == 2)
                or (ch == "一" and te == 1 and ta in (2, 4))
                or (te == 3 and ta == 2 and nxt_tone == 3)
                or (ta == 0)  # neutral tone written where the dictionary has a full tone (péngyou)
            )
            if not sandhi_ok:
                issues.append(Issue("warn", "tone", f"Tone of “{ch}” is written “{act_syl}”, dictionary says “{matched}”."))
        p += len(toneless(matched))
        i += 1

    if p < len(actual):
        issues.append(Issue("error", "extra_pinyin", f"Pinyin has extra syllables at the end (“{actual[p:p+10]}”)."))
    return issues
