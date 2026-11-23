"""
Reports as files. Every export is built from the same rows as the screen, and
carries who produced it, when, and under which filters.

Anything a person typed could reach a spreadsheet. A cell beginning with = + -
or @ is a formula to Excel, so text is always written as text.
"""
import csv
import io
import os
import re
from datetime import date, datetime
from decimal import Decimal
from xml.sax.saxutils import escape

import reportlab
from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from accounts.lab_zone import hour12
from accounts.models import LabConfig
from .engine import exported, text_of

CONTENT_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
FORMAT_NAMES = {"csv": "CSV", "xlsx": "Excel", "pdf": "PDF"}

# A cut-off report would look complete. Past these it is refused, with a reason.
ROW_LIMITS = {"csv": 50_000, "xlsx": 50_000, "pdf": 2_000}

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def _file_response(content, file_format: str, name: str) -> HttpResponse:
    moment = timezone.localtime().strftime("%Y%m%d-%H%M")
    response = HttpResponse(content, content_type=CONTENT_TYPES[file_format])
    # A batch number is typed by a person, and this is a response header.
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    response["Content-Disposition"] = f'attachment; filename="{safe_name}_{moment}.{file_format}"'
    return response


def _csv_text(value) -> str:
    text = text_of(value)
    if text.startswith(_FORMULA_START) and not _NUMBER.match(text):
        return "'" + text
    return text


def to_csv(meta: dict, columns: list, rows: list[dict]) -> HttpResponse:
    """A plain table for other tools to read; the date and time are in its file name."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([c.label for c in columns])
    for row in rows:
        writer.writerow([_csv_text(exported(row.get(c.key))) for c in columns])
    # The mark tells Excel it is UTF-8, so °, µ and – arrive intact.
    return _file_response("﻿" + out.getvalue(), "csv", meta["key"])


def _xlsx_write(sheet, row: int, column: int, value):
    if isinstance(value, datetime):
        cell = sheet.cell(row, column, timezone.localtime(value).replace(tzinfo=None))
        cell.number_format = "dd-mmm-yyyy hh:mm:ss AM/PM" if hour12() else "dd-mmm-yyyy hh:mm:ss"
    elif isinstance(value, date):
        cell = sheet.cell(row, column, value)
        cell.number_format = "dd-mmm-yyyy"
    elif isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        sheet.cell(row, column, value)
    else:
        cell = sheet.cell(row, column, ILLEGAL_CHARACTERS_RE.sub("", text_of(value)))
        cell.data_type = "s"  # text stays text, even if it begins with =


def to_xlsx(meta: dict, columns: list, rows: list[dict]) -> HttpResponse:
    book = Workbook()
    sheet = book.active
    sheet.title = meta["title"][:31]
    sheet["A1"] = meta["title"]
    sheet["A1"].font = Font(bold=True, size=14)
    lines = [
        f"Generated {meta['generated_at']} ({meta['timezone']}) by {meta['generated_by']}",
        *[f"{f['label']}: {f['value']}" for f in meta["applied"]],
        *([meta["note"]] if meta.get("note") else []),
        f"{len(rows)} rows",
    ]
    for offset, line in enumerate(lines, start=2):
        sheet.cell(offset, 1, line).font = Font(color="555555")
    head = len(lines) + 3
    for number, column in enumerate(columns, start=1):
        cell = sheet.cell(head, number, column.label)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="E6EBF4")
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        sheet.column_dimensions[get_column_letter(number)].width = max(12, min(44, 14 * column.width))
    for row_no, row in enumerate(rows, start=head + 1):
        for number, column in enumerate(columns, start=1):
            _xlsx_write(sheet, row_no, number, exported(row.get(column.key)))
    sheet.freeze_panes = sheet.cell(head + 1, 1)
    if rows:
        sheet.auto_filter.ref = f"A{head}:{get_column_letter(len(columns))}{head + len(rows)}"
    out = io.BytesIO()
    book.save(out)
    return _file_response(out.getvalue(), "xlsx", meta["key"])


# --- PDF -------------------------------------------------------------------

_FONT, _BOLD = "QCVera", "QCVera-Bold"
_INK, _MUTED, _RULE, _HEAD, _SERIES = (
    colors.HexColor("#0e1630"), colors.HexColor("#566180"), colors.HexColor("#cfd7e6"),
    colors.HexColor("#eef2f9"), colors.HexColor("#0d9488"),
)


def _fonts():
    """A font that carries α β µ ° ≥ ≤ ₁₂ and the dashes a limit is written with, embedded in the file."""
    if _FONT in pdfmetrics.getRegisteredFontNames():
        return
    folder = os.path.join(os.path.dirname(__file__), "fonts")
    pdfmetrics.registerFont(TTFont(_FONT, os.path.join(folder, "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(_BOLD, os.path.join(folder, "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily(_FONT, normal=_FONT, bold=_BOLD, italic=_FONT, boldItalic=_BOLD)


def _style(size: float, *, bold=False, color=_INK, after=0.0, leading=None) -> ParagraphStyle:
    return ParagraphStyle(
        "s", fontName=_BOLD if bold else _FONT, fontSize=size, leading=leading or size * 1.3,
        textColor=color, spaceAfter=after,
    )


def _para(text, style) -> Paragraph:
    # The embedded font has no arrow; nothing the system writes uses one.
    return Paragraph(escape(text_of(text)).replace("\n", "<br/>").replace("→", "-&gt;"), style)


class _Numbered(pdf_canvas.Canvas):
    """Page X of Y on every page, which is only known once the last page is drawn."""

    def __init__(self, *args, footer="", **kwargs):
        super().__init__(*args, **kwargs)
        self._pages = []
        self._footer = footer

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for number, page in enumerate(self._pages, start=1):
            self.__dict__.update(page)
            width = self._pagesize[0]
            self.setFont(_FONT, 7)
            self.setFillColor(_MUTED)
            self.drawString(12 * mm, 7 * mm, self._footer)
            self.drawRightString(width - 12 * mm, 7 * mm, f"Page {number} of {total}")
            super().showPage()
        super().save()


def _letterhead(cfg) -> list:
    lines = [_para(cfg.company_name or cfg.lab_name, _style(11, bold=True))]
    if cfg.company_name:
        lines.append(_para(cfg.lab_name, _style(8.5)))
    details = " · ".join(filter(None, [cfg.address.replace("\n", ", "), cfg.licence_no and f"Licence {cfg.licence_no}"]))
    if details:
        lines.append(_para(details, _style(7, color=_MUTED)))
    logo = None
    if cfg.logo:
        try:
            with cfg.logo.open("rb") as handle:
                data = io.BytesIO(handle.read())
            logo = Image(data, width=24 * mm, height=14 * mm, kind="proportional")
        except (FileNotFoundError, OSError):
            logo = None
    if logo is None:
        return lines
    block = Table([[logo, lines]], colWidths=[28 * mm, None])
    block.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return [block]


def _opening(meta: dict, cfg) -> list:
    story = _letterhead(cfg)
    story += [Spacer(1, 3 * mm), _para(meta["title"], _style(14, bold=True, after=1))]
    if meta.get("subtitle"):
        story.append(_para(meta["subtitle"], _style(9, color=_MUTED, after=1)))
    if meta.get("note"):
        story.append(_para(meta["note"], _style(7.5, color=_MUTED, after=2)))
    applied = " · ".join(f"{f['label']}: {f['value']}" for f in meta.get("applied", []))
    if applied:
        story.append(_para(applied, _style(7.5, after=2)))
    story.append(_para(
        f"Generated {meta['generated_at']} ({meta['timezone']}) by {meta['generated_by']}",
        _style(7.5, color=_MUTED, after=5),
    ))
    return story


def _table(labels: list, rows: list[list], widths: list[float], size: float) -> Table:
    head = _style(size, bold=True)
    body = _style(size)
    data = [[_para(label, head) for label in labels], *[[_para(v, body) for v in row] for row in rows]]
    # splitInRow: a long root cause runs on to the next page rather than failing the whole file.
    table = Table(data, colWidths=widths, repeatRows=1, splitInRow=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _HEAD),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, _RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    return table


def _render(story: list, footer: str, page_size) -> bytes:
    out = io.BytesIO()
    doc = SimpleDocTemplate(
        out, pagesize=page_size, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=13 * mm,
        title=footer,
    )
    doc.build(story, canvasmaker=lambda *a, **k: _Numbered(*a, footer=footer, **k))
    return out.getvalue()


def _widths(shares: list[float], total: float) -> list[float]:
    whole = sum(shares) or 1
    return [total * share / whole for share in shares]


def to_pdf(meta: dict, columns: list, rows: list[dict]) -> HttpResponse:
    _fonts()
    page = landscape(A4)
    size = max(5.8, 8.4 - 0.2 * len(columns))
    story = _opening({**meta, "subtitle": f"{len(rows)} rows"}, LabConfig.get())
    if rows:
        story.append(_table(
            [c.label for c in columns],
            [[exported(row.get(c.key)) for c in columns] for row in rows],
            _widths([c.width for c in columns], page[0] - 24 * mm), size,
        ))
    else:
        story.append(_para("Nothing matches these filters.", _style(9)))
    return _file_response(_render(story, f"{meta['title']}, generated {meta['generated_at']}", page), "pdf", meta["key"])


def _trend_drawing(part: dict, width: float) -> Drawing:
    """The trend as the screen draws it: one line, with the specification limits."""
    height = 42 * mm
    left, bottom, right, top = 26, 14, 8, 8
    plot_w, plot_h = width - left - right, height - bottom - top
    drawing = Drawing(width, height)
    points = part["points"]
    values = [p["y"] for p in points] + [v for v in (part["low"], part["high"]) if v is not None]
    low, high = min(values), max(values)
    margin = (high - low) * 0.08 or max(abs(high) * 0.05, 1)
    low, high = low - margin, high + margin

    def y_of(value):
        return bottom + (value - low) / (high - low) * plot_h

    def x_of(index):
        return left + (index / max(len(points) - 1, 1)) * plot_w

    drawing.add(Line(left, bottom, left + plot_w, bottom, strokeColor=_RULE, strokeWidth=0.5))
    for limit, label in ((part["low"], "Lower limit"), (part["high"], "Upper limit")):
        if limit is None:
            continue
        drawing.add(Line(left, y_of(limit), left + plot_w, y_of(limit), strokeColor=_MUTED, strokeWidth=0.5,
                         strokeDashArray=[3, 2]))
        drawing.add(String(left + 2, y_of(limit) + 2, f"{label} {limit:g}", fontName=_FONT, fontSize=6, fillColor=_MUTED))
    drawing.add(PolyLine(
        [c for i, p in enumerate(points) for c in (x_of(i), y_of(p["y"]))], strokeColor=_SERIES, strokeWidth=1.2,
    ))
    for i, p in enumerate(points):
        fill = colors.HexColor("#b91c1c") if p["outcome"] == "FAIL" else _SERIES
        drawing.add(Circle(x_of(i), y_of(p["y"]), 1.8, fillColor=fill, strokeColor=colors.white, strokeWidth=0.4))
    for value in (min(p["y"] for p in points), max(p["y"] for p in points)):
        scale = String(left - 3, y_of(value) - 2, f"{value:g}", fontName=_FONT, fontSize=6, fillColor=_MUTED)
        scale.textAnchor = "end"
        drawing.add(scale)
    drawing.add(String(left, 2, points[0]["label"][:11], fontName=_FONT, fontSize=6, fillColor=_MUTED))
    last = String(left + plot_w, 2, points[-1]["label"][:11], fontName=_FONT, fontSize=6, fillColor=_MUTED)
    last.textAnchor = "end"
    drawing.add(last)
    return drawing


def _document_part(part: dict, width: float) -> list:
    if part["kind"] == "facts":
        items = part["items"]
        rows = [items[i:i + 3] for i in range(0, len(items), 3)]
        key, value = _style(6.5, color=_MUTED), _style(8, bold=True)
        data = [
            [[_para(cell["label"], key), _para(cell["value"], value)] for cell in row] + [""] * (3 - len(row))
            for row in rows
        ]
        table = Table(data, colWidths=[width / 3] * 3)
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ]))
        return [table, Spacer(1, 2 * mm)]
    if part["kind"] == "note":
        return [_para(part["text"], _style(7.5, color=_MUTED, after=3))]
    if part["kind"] == "trend":
        return [KeepTogether([
            _para(part["heading"], _style(8.5, bold=True)),
            _para(part["sub"], _style(7, color=_MUTED)),
            _trend_drawing(part, width),
        ]), Spacer(1, 2 * mm)]

    story = [_para(part["heading"], _style(8.5, bold=True, after=1.5))] if part["heading"] else []
    if not part["rows"]:
        return [*story, _para(part["empty"], _style(7.5, color=_MUTED, after=4))]
    columns = part["columns"]

    def shown(cell) -> str:
        if isinstance(cell, dict):
            return " — ".join(filter(None, [cell["text"], cell.get("sub", "")]))
        return cell

    size = max(6, 7.8 - 0.15 * len(columns))
    story.append(_table(
        [c["label"] for c in columns], [[shown(row[c["key"]]) for c in columns] for row in part["rows"]],
        _widths([c["width"] for c in columns], width), size,
    ))
    return [*story, Spacer(1, 3 * mm)]


def document_pdf(doc: dict, meta: dict, name: str) -> HttpResponse:
    _fonts()
    page = landscape(A4)
    width = page[0] - 24 * mm
    story = _opening({
        **meta, "title": doc["title"], "subtitle": f"{doc['reference']}: {doc['subtitle']}",
        "applied": [{"label": "Period", "value": doc["period"]}] if doc.get("period") else [],
    }, LabConfig.get())
    for section in doc["sections"]:
        parts = [p for part in section["parts"] for p in _document_part(part, width)]
        heading = _para(section["title"], _style(10, bold=True, after=2.5))
        story += [KeepTogether([heading, *parts[:1]]), *parts[1:], Spacer(1, 2 * mm)]
    footer = f"{doc['title']} {doc['reference']}, generated {meta['generated_at']}"
    return _file_response(_render(story, footer, page), "pdf", name)

