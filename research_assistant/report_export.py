"""Member 6 Markdown/PDF exports. Imports PDF dependencies only when needed."""
from __future__ import annotations

from io import BytesIO
import html
from pathlib import Path
import re

from .schemas import FinalReport


def markdown_bytes(report: dict) -> bytes:
    return FinalReport.model_validate(report).markdown.encode("utf-8")


def _text(value: str) -> str:
    value = re.sub(r"(?<!!)\[([^\]]+)\]\((https?://[^\s]+)\)", r"\1 (\2)", value)
    value = re.sub(r"\\([\\`*_{}\[\]()#+.!|>~])", r"\1", value)
    return html.unescape(value.replace("**", "").replace("`", ""))


def pdf_bytes(report: dict) -> bytes:
    """Export the generated report dialect, including wrapped repeating tables."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle

    parsed = FinalReport.model_validate(report)
    font = "Member6CJK"
    if font not in pdfmetrics.getRegisteredFontNames():
        # Embed an available CJK TrueType font on Windows; standard CID fallback elsewhere.
        candidate = Path("C:/Windows/Fonts/simsun.ttc")
        if candidate.is_file():
            pdfmetrics.registerFont(TTFont(font, str(candidate), subfontIndex=0))
        else:
            font = "STSong-Light"
            if font not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(UnicodeCIDFont(font))
    normal = ParagraphStyle("report", fontName=font, fontSize=10, leading=16, wordWrap="CJK", spaceAfter=7)
    small = ParagraphStyle("cell", parent=normal, fontSize=8, leading=12, spaceAfter=0)
    styles = {level: ParagraphStyle(f"h{level}", parent=normal, fontSize=size, leading=size+8,
                                    spaceBefore=12, spaceAfter=8, keepWithNext=True)
              for level, size in [(1, 22), (2, 15), (3, 11)]}
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=40, leftMargin=40,
                            topMargin=40, bottomMargin=42, title=parsed.title, author="Research Assistant")
    flow = []

    def para(text, style=normal):
        return Paragraph(html.escape(_text(text)).replace("\n", "<br/>"), style)

    lines = parsed.markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if line.startswith("|"):
            table = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                cells = re.split(r"(?<!\\)\|", lines[index].strip())[1:-1]
                if not all(re.fullmatch(r"\s*:?-+:?\s*", c) for c in cells):
                    table.append([para(c.strip(), small) for c in cells])
                index += 1
            count = max((len(row) for row in table), default=0)
            if count:
                table = [row + [para("", small)] * (count - len(row)) for row in table]
                widths = ([28] + [(doc.width-28)/(count-1)]*(count-1)) if count > 1 else [doc.width]
                block = LongTable(table, colWidths=widths, repeatRows=1, splitInRow=1, hAlign="LEFT")
                block.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c9d2df")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]))
                flow += [block, Spacer(1, 8)]
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)", line)
        if heading:
            flow.append(para(heading[2], styles[len(heading[1])]))
        elif line:
            flow.append(para(line[2:] if line.startswith("> ") else line))
        index += 1

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#52647b"))
        canvas.drawString(40, 23, "Research Assistant")
        canvas.drawRightString(A4[0]-40, 23, str(document.page))
        canvas.restoreState()

    doc.build(flow or [para("空报告")], onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
