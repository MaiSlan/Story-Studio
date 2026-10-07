"""Build the bundled CJK font used by the PDF renderer.

Why this exists
---------------
ReportLab (the PDF library) can only embed TrueType-flavoured fonts (glyf outlines).
Noto Sans CJK ships as CFF-flavoured OpenType collections, so we:

  1. pick the Simplified-Chinese face out of the .ttc collection,
  2. subset it to what the stories need (Latin + pinyin tone marks, punctuation,
     and the whole CJK Unified Ideographs block),
  3. convert the cubic CFF outlines to quadratic TrueType outlines,
  4. save fonts/NotoSansSC-Subset.ttf

You only need to run this if you want to rebuild the font (for example from a
different weight). The generated file is already included in the project.

    python tools/build_cjk_font.py [path/to/NotoSansCJK-Regular.ttc]

Noto Sans CJK is licensed under the SIL Open Font License 1.1 (see fonts/LICENSES).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from fontTools import subset
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTCollection, TTFont, newTable

DEFAULT_SRC = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
OUT = Path(__file__).resolve().parent.parent / "fonts" / "NotoSansSC-Subset.ttf"


def wanted_codepoints() -> list[int]:
    cps: set[int] = set()
    cps.update(range(0x20, 0x7F))        # ASCII
    cps.update(range(0xA0, 0x250))       # Latin-1, Latin Extended-A/B (ā ǎ ǖ é ç œ ...)
    cps.update(range(0x250, 0x2B0))      # IPA extensions (ɑ ɡ, used in pinyin)
    cps.update(range(0x300, 0x370))      # combining diacritics
    cps.update(range(0x2000, 0x2070))    # general punctuation (“ ” ‘ ’ — …)
    cps.update(range(0x3000, 0x3040))    # CJK punctuation (、 。 《 》 「 」)
    cps.update(range(0x4E00, 0xA000))    # CJK Unified Ideographs
    cps.update(range(0xFF00, 0xFFF0))    # full-width forms (，！？：；（）)
    return sorted(cps)


def pick_sc_face(path: str) -> TTFont:
    coll = TTCollection(path)
    for font in coll.fonts:
        family = font["name"].getDebugName(1) or ""
        if family.strip() == "Noto Sans CJK SC":
            return font
    raise SystemExit("Could not find 'Noto Sans CJK SC' in " + path)


def glyphs_to_quadratic(glyph_set, max_err=1.0):
    quad = {}
    for name in glyph_set.keys():
        pen = TTGlyphPen(glyph_set)
        glyph_set[name].draw(Cu2QuPen(pen, max_err, reverse_direction=True))
        quad[name] = pen.glyph()
    return quad


def otf_to_ttf(font: TTFont) -> None:
    order = font.getGlyphOrder()
    font["loca"] = newTable("loca")
    font["glyf"] = glyf = newTable("glyf")
    glyf.glyphOrder = order
    glyf.glyphs = glyphs_to_quadratic(font.getGlyphSet())
    del font["CFF "]
    if "VORG" in font:
        del font["VORG"]
    glyf.compile(font)

    hmtx = font["hmtx"]
    for name, glyph in glyf.glyphs.items():
        if hasattr(glyph, "xMin"):
            hmtx[name] = (hmtx[name][0], glyph.xMin)

    font["maxp"] = maxp = newTable("maxp")
    maxp.tableVersion = 0x00010000
    maxp.numGlyphs = len(order)
    maxp.maxZones = 1
    maxp.maxTwilightPoints = 0
    maxp.maxStorage = 0
    maxp.maxFunctionDefs = 0
    maxp.maxInstructionDefs = 0
    maxp.maxStackElements = 0
    maxp.maxSizeOfInstructions = 0
    maxp.maxComponentElements = max(
        (len(getattr(g, "components", [])) for g in glyf.glyphs.values()), default=0
    )
    maxp.maxPoints = maxp.maxContours = maxp.maxCompositePoints = 0
    maxp.maxCompositeContours = maxp.maxComponentDepth = 0
    maxp.maxSizeOfInstructions = 0

    post = font["post"]
    post.formatType = 2.0
    post.extraNames = []
    post.mapping = {}
    post.glyphOrder = order
    font.sfntVersion = "\x00\x01\x00\x00"


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    t0 = time.time()
    font = pick_sc_face(src)
    print(f"loaded {src} ({time.time() - t0:.1f}s)")

    opts = subset.Options()
    opts.layout_features = []          # no OpenType layout tables needed
    opts.hinting = False
    opts.notdef_outline = True
    opts.glyph_names = False
    opts.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14]
    opts.drop_tables += ["GSUB", "GPOS", "GDEF", "vhea", "vmtx", "VORG"]
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=wanted_codepoints())
    sub.subset(font)
    print(f"subset to {len(font.getGlyphOrder())} glyphs ({time.time() - t0:.1f}s)")

    otf_to_ttf(font)
    print(f"converted outlines to TrueType ({time.time() - t0:.1f}s)")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    font.save(OUT)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB) in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
