#!/usr/bin/env python3
"""Build the PDF companion to the AOI simulation Markdown report."""

from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reports" / "aoi-25m-bcdem-summer-p90.md"
OUTPUT = ROOT / "output" / "pdf" / "aoi-25m-bcdem-summer-p90-report.pdf"
MAP_IMAGE = ROOT / "runs" / "aoi-25m-bcdem-summer-p90" / "outputs" / "burn_probability.png"

INK = colors.HexColor("#24313a")
MUTED = colors.HexColor("#5d6b74")
BLUE = colors.HexColor("#245b78")
PALE_BLUE = colors.HexColor("#eaf2f6")
RULE = colors.HexColor("#c7d2d9")
PALE_GOLD = colors.HexColor("#fbf3dd")


def ascii_dashes(text: str) -> str:
    return text.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")


def inline_markup(text: str) -> str:
    """Convert the limited inline Markdown used by the report to ReportLab XML."""
    text = ascii_dashes(text)
    tokens: list[str] = []

    def stash(value: str) -> str:
        tokens.append(value)
        return f"@@TOKEN{len(tokens) - 1}@@"

    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: stash(
            f'<link href="{escape(str((SOURCE.parent / m.group(2)).resolve()) if "://" not in m.group(2) else m.group(2))}" '
            f'color="#245b78"><u>{escape(m.group(1).strip("`").replace("\\[", "[").replace("\\]", "]"))}</u></link>'
        ),
        text,
    )
    text = re.sub(r"`([^`]+)`", lambda m: stash(f'<font name="Courier">{escape(m.group(1))}</font>'), text)
    text = escape(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    for index, token in enumerate(tokens):
        text = text.replace(f"@@TOKEN{index}@@", token)
    return text


def page_chrome(canvas, doc) -> None:
    canvas.saveState()
    width, height = letter
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(0.65 * inch, height - 0.48 * inch, width - 0.65 * inch, height - 0.48 * inch)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(0.65 * inch, height - 0.35 * inch, "AOI fire-spread simulation")
    canvas.drawRightString(width - 0.65 * inch, 0.38 * inch, f"Page {doc.page}")
    canvas.restoreState()


def styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=23,
            leading=28,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=14,
        ),
        "h2": ParagraphStyle(
            "Section",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=BLUE,
            spaceBefore=12,
            spaceAfter=7,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13.2,
            textColor=INK,
            spaceAfter=7,
        ),
        "table_header": ParagraphStyle(
            "TableHeader",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9.3,
            leading=11.5,
            textColor=colors.white,
        ),
        "table_number": ParagraphStyle(
            "TableNumber",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13.2,
            textColor=INK,
            alignment=2,
        ),
        "bullet": ParagraphStyle(
            "BulletBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.3,
            leading=12.5,
            textColor=INK,
            leftIndent=4,
        ),
        "caption": ParagraphStyle(
            "Caption",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=8.2,
            leading=11,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceBefore=4,
            spaceAfter=10,
        ),
        "footer_note": ParagraphStyle(
            "FooterNote",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=10.5,
            textColor=MUTED,
        ),
    }


def table_from_lines(lines: list[str], report_styles) -> Table:
    rows = []
    numeric = len([cell for cell in lines[0].strip().strip("|").split("|")]) == 3
    for row_index, line in enumerate(lines):
        values = [cell.strip() for cell in line.strip().strip("|").split("|")]
        cells = []
        for column_index, value in enumerate(values):
            cell_style = report_styles["table_header"] if row_index == 0 else report_styles["body"]
            if numeric and row_index > 0 and column_index > 0:
                cell_style = report_styles["table_number"]
            cells.append(Paragraph(inline_markup(value), cell_style))
        rows.append(cells)
    header, body = rows[0], rows[2:]
    rows = [header, *body]
    widths = [2.05 * inch, 1.45 * inch, 1.45 * inch] if numeric else [1.72 * inch, 5.0 * inch]
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for row in range(1, len(rows)):
        commands.append(("BACKGROUND", (0, row), (-1, row), colors.white if row % 2 else PALE_BLUE))
    if numeric:
        commands.extend(
            [
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("FONTNAME", (1, 1), (-1, -1), "Helvetica"),
            ]
        )
    table.setStyle(TableStyle(commands))
    return table


def build_story() -> list:
    text = SOURCE.read_text(encoding="utf-8")
    lines = text.splitlines()
    report_styles = styles()
    story: list = []
    index = 0
    title_done = False

    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith("# "):
            story.extend(
                [
                    Spacer(1, 0.18 * inch),
                    Paragraph(inline_markup(line[2:]), report_styles["title"]),
                    HRFlowable(width="100%", thickness=2, color=BLUE, spaceAfter=12),
                    Paragraph(
                        "Technical report | Corrected 25 m terrain scenario | 1,028 completed simulations",
                        report_styles["footer_note"],
                    ),
                    Spacer(1, 0.12 * inch),
                ]
            )
            title_done = True
            index += 1
            continue
        if line.startswith("## "):
            if title_done and line == "## Burn probability surface":
                story.append(PageBreak())
            story.append(Paragraph(inline_markup(line[3:]), report_styles["h2"]))
            index += 1
            continue
        if line.startswith("!["):
            if MAP_IMAGE.exists():
                image = Image(str(MAP_IMAGE), width=5.15 * inch, height=5.33 * inch)
                story.append(
                    KeepTogether(
                        [
                            image,
                            Paragraph(
                                "Cell2Fire burn-frequency surface. Warmer colours indicate cells reached by more of the 1,028 ignition scenarios.",
                                report_styles["caption"],
                            ),
                        ]
                    )
                )
            index += 1
            continue
        if line.startswith("|"):
            table_lines = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index].strip())
                index += 1
            story.append(table_from_lines(table_lines, report_styles))
            story.append(Spacer(1, 0.08 * inch))
            continue
        if line.startswith("- "):
            items = []
            while index < len(lines) and lines[index].strip().startswith("- "):
                items.append(
                    ListItem(
                        Paragraph(inline_markup(lines[index].strip()[2:]), report_styles["bullet"]),
                        leftIndent=12,
                    )
                )
                index += 1
            story.append(ListFlowable(items, bulletType="bullet", start="circle", leftIndent=16, bulletFontSize=6))
            story.append(Spacer(1, 0.05 * inch))
            continue
        if re.match(r"^\d+\. ", line):
            items = []
            while index < len(lines) and re.match(r"^\d+\. ", lines[index].strip()):
                item = re.sub(r"^\d+\. ", "", lines[index].strip())
                items.append(ListItem(Paragraph(inline_markup(item), report_styles["bullet"]), leftIndent=16))
                index += 1
            story.append(ListFlowable(items, bulletType="1", leftIndent=20, bulletFontSize=8))
            story.append(Spacer(1, 0.05 * inch))
            continue

        paragraph = [line]
        index += 1
        while index < len(lines):
            nxt = lines[index].strip()
            if not nxt or nxt.startswith(("#", "|", "-", "![")) or re.match(r"^\d+\. ", nxt):
                break
            paragraph.append(nxt)
            index += 1
        story.append(Paragraph(inline_markup(" ".join(paragraph)), report_styles["body"]))

    return story


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=letter,
        rightMargin=0.65 * inch,
        leftMargin=0.65 * inch,
        topMargin=0.62 * inch,
        bottomMargin=0.58 * inch,
        title="AOI fire-spread simulation: BC 25 m DEM and summer P90 weather",
        author="Fire Probability project",
        subject="Technical report for the corrected AOI Cell2Fire simulation",
    )
    document.build(build_story(), onFirstPage=page_chrome, onLaterPages=page_chrome)
    print(OUTPUT)


if __name__ == "__main__":
    main()
