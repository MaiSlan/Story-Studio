"""PDF renderer (ReportLab).

Layout, as in the original stories:
    1   Bold primary line (pinyin or French)  - the line to read aloud
        Grey simplified hanzi below it
        Small italic English gloss underneath
"""
from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .config import FONT_DIR
from .models import Story
from .tracks import TRACKS

_FONTS_READY = False

INK = colors.HexColor("#1b1b1f")
GREY = colors.HexColor("#7a7a85")
ENGLISH = colors.HexColor("#4a4a55")
ACCENT = colors.HexColor("#9c3b2e")
RULE = colors.HexColor("#e4e0d8")


def _register_fonts() -> None:
    global _FONTS_READY
    if _FONTS_READY:
        return
    for name, file in (
        ("Latin", "DejaVuSans.ttf"),
        ("Latin-Bold", "DejaVuSans-Bold.ttf"),
        ("Latin-Italic", "DejaVuSans-Oblique.ttf"),
        ("Latin-BoldItalic", "DejaVuSans-BoldOblique.ttf"),
        ("CJK", "NotoSansSC-Subset.ttf"),
    ):
        pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))
    pdfmetrics.registerFontFamily("Latin", normal="Latin", bold="Latin-Bold", italic="Latin-Italic", boldItalic="Latin-BoldItalic")
    _FONTS_READY = True


def _styles(scale: float = 1.0) -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle("title", fontName="Latin-Bold", fontSize=21 * scale, leading=27 * scale, textColor=INK, alignment=TA_LEFT),
        "title_zh": ParagraphStyle("title_zh", fontName="CJK", fontSize=17 * scale, leading=24 * scale, textColor=GREY, wordWrap="CJK"),
        "title_en": ParagraphStyle("title_en", fontName="Latin-Italic", fontSize=11 * scale, leading=15 * scale, textColor=ENGLISH),
        "meta": ParagraphStyle("meta", fontName="Latin", fontSize=8 * scale, leading=11 * scale, textColor=ACCENT),
        "primary": ParagraphStyle("primary", fontName="Latin-Bold", fontSize=13 * scale, leading=17.5 * scale, textColor=INK),
        "zh": ParagraphStyle("zh", fontName="CJK", fontSize=12 * scale, leading=16.5 * scale, textColor=GREY, wordWrap="CJK", spaceBefore=1.5),
        "en": ParagraphStyle("en", fontName="Latin-Italic", fontSize=8.8 * scale, leading=12 * scale, textColor=ENGLISH, spaceBefore=1.5),
        "num": ParagraphStyle("num", fontName="Latin", fontSize=8 * scale, leading=17.5 * scale, textColor=GREY, alignment=2),
    }


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text), style)


def render_pdf(story: Story, font_scale: float = 1.0) -> bytes:
    _register_fonts()
    track = TRACKS[story.track]
    st = _styles(font_scale)
    buf = io.BytesIO()
    page_w, _ = A4
    margin = 20 * mm
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=18 * mm, bottomMargin=18 * mm,
        title=story.title.english or story.title.primary, author="Story Studio",
    )

    flow: list = []
    if story.title.primary:
        flow.append(_p(story.title.primary, st["title"]))
    if story.title.hanzi:
        flow.append(_p(story.title.hanzi, st["title_zh"]))
    if story.title.english:
        flow.append(_p(story.title.english, st["title_en"]))
    flow.append(Spacer(1, 3 * mm))
    meta = f"{track.pdf_subtitle.upper()}   ·   LEVEL {story.level}   ·   {len(story.lines)} LINES"
    flow.append(_p(meta, st["meta"]))
    flow.append(Spacer(1, 2 * mm))
    flow.append(HRFlowable(width="100%", thickness=0.8, color=ACCENT, spaceAfter=5 * mm))

    num_w = 11 * mm
    content_w = page_w - 2 * margin - num_w
    rows = []
    for ln in story.lines:
        cell = [_p(ln.primary, st["primary"]), _p(ln.hanzi, st["zh"]), _p(ln.english, st["en"])]
        rows.append([_p(str(ln.n), st["num"]), cell])

    # one table row per story line; ReportLab splits the table across pages between rows
    tbl = Table(rows, colWidths=[num_w, content_w], splitByRow=1)
    tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, -1), 4 * mm),
                ("RIGHTPADDING", (1, 0), (1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 2.1 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.1 * mm),
                ("LINEBELOW", (0, 0), (-1, -2), 0.3, RULE),
            ]
        )
    )
    flow.append(tbl)

    short_title = (story.title.english or story.title.primary)[:60]

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Latin", 7.5)
        canvas.setFillColor(GREY)
        canvas.drawString(margin, 10 * mm, short_title)
        canvas.drawRightString(page_w - margin, 10 * mm, f"{d.page}")
        canvas.restoreState()

    doc.build(flow, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
