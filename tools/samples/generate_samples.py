#!/usr/bin/env python3
"""Generate fictional SAMPLE marketplace images and PDFs.

Outputs land in assets/samples/. The pictures show a made-up contractor,
North Pine Demo Builders, and a made-up job, NP-1042. They do not name a
studio brand, and they do not carry contact details.

Run from the repository root:

    .venv/bin/python tools/samples/generate_samples.py
"""

from __future__ import annotations

import argparse
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
from reportlab.lib.colors import Color, white
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[2]
FONT_DIR = Path(__file__).resolve().parent / "fonts"
DEFAULT_OUT = ROOT / "assets" / "samples"

PINE = (23, 56, 44)
PINE_DEEP = (14, 36, 28)
PAPER = (246, 243, 236)
INK = (26, 35, 50)
MUTED = (90, 99, 110)
LINE = (221, 214, 202)
WHITE = (255, 255, 255)
BRASS = (184, 146, 74)
GOLD = (232, 208, 150)
MIST = (228, 239, 232)
BRICK = (148, 58, 48)
BRICK_BG = (247, 232, 228)
OCHRE = (122, 90, 32)
OCHRE_BG = (245, 236, 214)
SLATE_FG = (52, 74, 92)
SLATE_BG = (226, 234, 238)
SAGE_BG = (228, 240, 232)
SHADOW = (232, 226, 216)
SAGE = (126, 154, 134)
CLAY = (196, 164, 132)
SLATE = (143, 164, 176)
DUST = (205, 184, 146)
EMPTY = (236, 231, 222)

CABINET = Decimal("4800.00")
ELECTRICAL = Decimal("640.00")
SUBTOTAL = CABINET + ELECTRICAL

FOOTER = "SAMPLE — fictional data — not a real client"
COVER_FOOTER = "North Pine Demo Builders · fictional job NP-1042 · not a real client"

BANNED = (
    "contractorflow",
    "quotetrail",
    "tradefile",
    "sitepacket",
    "studio_name",
    "[studio_name]",
    "fiverr",
    "upwork",
    "linkedin",
    "buildertrend",
    "xactimate",
    "servicem8",
    "instagram",
    "facebook",
    "twitter",
    "tiktok",
    "whatsapp",
    "telegram",
    "testimonial",
    "certified",
    "certification",
    "revenue",
    "employees",
    "our team",
    "headcount",
    "united states office",
    "u.s. office",
    "us office",
    "production software",
    "production-ready",
    "@",
    "http://",
    "https://",
    "www.",
    ".com",
    ".net",
    ".org",
    "gmail",
    "hotmail",
    "e-mail",
    "email",
    "phone",
    "qr code",
    "qrcode",
    " street",
    " avenue",
    " road",
    " drive",
    " lane",
    " boulevard",
    " highway",
    " suite",
)

PHONE_RE = re.compile(
    r"(?:"
    r"\(\d{3}\)\s*\d{3}[-.\s]\d{4}"
    r"|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"
    r"|\b\d{4}\s\d{3}\s\d{3}\b"
    r"|\+\d{1,3}[\s.-]\(?\d{2,4}\)?[\s.-]\d{3,4}[\s.-]\d{3,4}"
    r")"
)

_FONTS: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    key = (kind, size)
    if key not in _FONTS:
        filename = {
            "regular": "LiberationSans-Regular.ttf",
            "bold": "LiberationSans-Bold.ttf",
            "mono": "LiberationMono-Regular.ttf",
        }[kind]
        _FONTS[key] = ImageFont.truetype(str(FONT_DIR / filename), size)
    return _FONTS[key]


def fit_font(kind: str, text: str, max_width: float, start: int, minimum: int = 12):
    size = start
    while size > minimum and font(kind, size).getlength(text) > max_width:
        size -= 1
    return font(kind, size)


def money(value: Decimal) -> str:
    quant = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{quant:,.2f}"


def outside(bbox, box, slack=0.8) -> bool:
    x0, y0, x1, y1 = bbox
    left, top, right, bottom = box
    return x0 < left - slack or y0 < top - slack or x1 > right + slack or y1 > bottom + slack


class Art:
    """RGB canvas that remembers every string and the box it must fit."""

    def __init__(self, width: int, height: int, fill: tuple[int, int, int]):
        self.image = Image.new("RGB", (width, height), fill)
        self.draw = ImageDraw.Draw(self.image)
        self.texts: list[str] = []
        self.placements: list[tuple[str, tuple, tuple]] = []
        self.w = width
        self.h = height

    def text(self, xy, value, face, fill, anchor="lt", box=None):
        if value:
            self.texts.append(value)
        bbox = self.draw.textbbox(xy, value, font=face, anchor=anchor)
        limit = box if box is not None else (1, 1, self.w - 1, self.h - 1)
        self.placements.append((value, bbox, limit))
        self.draw.text(xy, value, font=face, fill=fill, anchor=anchor)

    def overflows(self) -> list[str]:
        found = []
        for value, bbox, limit in self.placements:
            if outside(bbox, limit):
                snippet = value if len(value) <= 48 else value[:45] + "..."
                found.append(f"{snippet!r} bbox {tuple(round(v, 1) for v in bbox)} outside {tuple(round(v, 1) for v in limit)}")
        return found

    def save(self, path: Path):
        self.image.save(path, "PNG", dpi=(72, 72))


def rounded(art: Art, box, radius, fill, outline=None, width=1):
    art.draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def card(art: Art, x, y, w, h, radius=16):
    art.draw.rounded_rectangle((x + 4, y + 5, x + w + 4, y + h + 5), radius=radius, fill=SHADOW)
    rounded(art, (x, y, x + w, y + h), radius, WHITE)


def pill(art: Art, right, cy, label, fg, bg, face, width, bounds=None):
    height = face.size + 18
    x = right - width
    y = cy - height / 2
    rect = (x, y, x + width, y + height)
    rounded(art, rect, height / 2, bg)
    if bounds is not None:
        art.placements.append((f"{label} pill", rect, bounds))
    art.text((x + width / 2, cy), label, face, fg, "mm", box=(x + 6, y + 2, x + width - 6, y + height - 2))


def checkbox(art: Art, x, y, size, checked):
    color = BRICK if checked else (186, 178, 166)
    art.draw.rounded_rectangle((x, y, x + size, y + size), radius=4, outline=color, width=2)
    if checked:
        art.draw.line(
            (x + size * 0.22, y + size * 0.52, x + size * 0.42, y + size * 0.74),
            fill=BRICK,
            width=3,
        )
        art.draw.line(
            (x + size * 0.42, y + size * 0.74, x + size * 0.78, y + size * 0.28),
            fill=BRICK,
            width=3,
        )


def hairline(art: Art):
    bar = max(6, art.h // 110)
    art.draw.rectangle((0, 0, art.w, bar), fill=PINE)
    art.draw.rectangle((0, art.h - bar, art.w, art.h), fill=PINE)


def kicker(art: Art, y):
    sample_size = max(40, int(art.h * 0.072))
    face = font("bold", sample_size)
    x = int(art.w * 0.05)
    row_bottom = y + sample_size + 4
    art.text((x, y), "SAMPLE", face, PINE, "lt", box=(x, y, art.w * 0.46, row_bottom))
    note_size = max(22, int(art.h * 0.034))
    note = font("bold", note_size)
    label = "Fictional data"
    art.text(
        (art.w - x - 2, y + (sample_size - note_size) / 2),
        label,
        note,
        PINE,
        "rt",
        box=(art.w * 0.54, y, art.w - x, row_bottom),
    )
    return y + sample_size


def footer_line(art: Art, text):
    """Draw the cover footer in the band above the bottom rule, fully inside that band."""
    bar = max(6, art.h // 110)
    margin = max(28, int(art.w * 0.045))
    band_bottom = art.h - bar - 8
    band_top = band_bottom - max(28, int(art.h * 0.055))
    box = (margin, band_top, art.w - margin, band_bottom)
    size = max(15, int(art.h * 0.023))
    face = font("regular", size)
    while size > 13 and face.getlength(text) > (box[2] - box[0]):
        size -= 1
        face = font("regular", size)
    art.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), text, face, MUTED, "mm", box=box)


def cover_packet(w, h):
    art = Art(w, h, PAPER)
    left = int(w * 0.38)
    art.draw.rectangle((0, 0, left, h), fill=PINE)
    art.draw.rectangle((left, 0, left + 6, h), fill=BRASS)
    pad = int(left * 0.09)
    panel = (pad, 12, left - 16, h - 12)
    sample = fit_font("bold", "SAMPLE", left - pad * 2, max(42, int(h * 0.078)))
    art.text((pad, int(h * 0.09)), "SAMPLE", sample, GOLD, "lt", box=panel)
    title_size = max(52, int(h * 0.118))
    quote = fit_font("bold", "Quote", left - pad * 2, title_size)
    packet = fit_font("bold", "Packet", left - pad * 2, title_size)
    y = int(h * 0.20)
    art.text((pad, y), "Quote", quote, WHITE, "lt", box=panel)
    y += int(quote.size * 1.02)
    art.text((pad, y), "Packet", packet, WHITE, "lt", box=panel)
    y += int(packet.size * 1.18)
    art.draw.rectangle((pad, y, pad + int(left * 0.22), y + 4), fill=BRASS)
    y += int(h * 0.045)
    sub = fit_font("bold", "Before and after", left - pad * 2, max(24, int(h * 0.042)))
    art.text((pad, y), "Before and after", sub, MIST, "lt", box=panel)
    company = fit_font("regular", "North Pine Demo Builders", left - pad * 2, max(16, int(h * 0.028)))
    job = fit_font("regular", "Fictional job NP-1042", left - pad * 2, max(15, int(h * 0.024)))
    art.text((pad, h - int(h * 0.145)), "North Pine Demo Builders", company, MIST, "lt", box=panel)
    art.text((pad, h - int(h * 0.098)), "Fictional job NP-1042", job, (186, 214, 198), "lt", box=panel)
    art.text((pad, h - int(h * 0.055)), "Fictional data", font("bold", max(16, int(h * 0.026))), GOLD, "lt", box=panel)

    gap = int(w * 0.018)
    outer = int(w * 0.028)
    right = left + 6
    area_w = w - right - outer
    card_w = (area_w - outer - gap) // 2
    card_h = int(h * 0.74)
    card_y = (h - card_h) // 2
    _before_card(art, right + outer, card_y, card_w, card_h)
    _after_card(art, right + outer + card_w + gap, card_y, card_w, card_h)
    return art


def _before_card(art: Art, x, y, w, h):
    card(art, x, y, w, h)
    inner = (x + 16, y + 16, x + w - 16, y + h - 12)
    art.draw.rounded_rectangle((x, y, x + w, y + 10), radius=8, fill=BRICK)
    art.draw.rectangle((x, y + 6, x + w, y + 12), fill=BRICK)
    label = fit_font("bold", "BEFORE", w - 40, max(26, int(h * 0.07)))
    art.text((x + 24, y + int(h * 0.07)), "BEFORE", label, BRICK, "lt", box=inner)
    names = ["IMG_4481.jpg", "quote FINAL v7.pdf", "scan (3).pdf", "site notes.docx"]
    top = y + int(h * 0.20)
    bottom = y + h - int(h * 0.12)
    row_h = (bottom - top) / len(names)
    face_size = max(15, int(min(w, h) * 0.055))
    for index, name in enumerate(names):
        cy = top + row_h * index + row_h / 2
        indent = (8, 28, 4, 22)[index]
        art.draw.ellipse((x + 20 + indent, cy - 5, x + 32 + indent, cy + 7), fill=CLAY)
        face = fit_font("mono", name, w - 72 - indent, face_size, 12)
        art.text((x + 40 + indent, cy), name, face, INK, "lm", box=inner)
    cap = font("regular", max(13, int(h * 0.038)))
    art.text((x + 24, y + h - int(h * 0.065)), "Names as received", cap, MUTED, "lt", box=inner)


def _after_card(art: Art, x, y, w, h):
    card(art, x, y, w, h)
    inner = (x + 16, y + 16, x + w - 16, y + h - 12)
    art.draw.rectangle((x, y + 6, x + w, y + 12), fill=PINE)
    art.draw.rounded_rectangle((x, y, x + w, y + 10), radius=8, fill=PINE)
    label = fit_font("bold", "AFTER", w - 40, max(26, int(h * 0.07)))
    art.text((x + 24, y + int(h * 0.07)), "AFTER", label, PINE, "lt", box=inner)
    rows = [("01", "Site notes"), ("02", "Cabinet quote"), ("03", "Follow-up list"), ("04", "Photo names")]
    top = y + int(h * 0.20)
    bottom = y + h - int(h * 0.12)
    row_h = (bottom - top) / len(rows)
    radius = max(16, int(min(row_h, w) * 0.28))
    for index, (number, name) in enumerate(rows):
        cy = top + row_h * index + row_h / 2
        art.draw.ellipse((x + 24, cy - radius, x + 24 + radius * 2, cy + radius), fill=PINE)
        num_face = fit_font("bold", number, radius * 1.6, max(12, int(radius * 0.8)), 10)
        art.text(
            (x + 24 + radius, cy),
            number,
            num_face,
            WHITE,
            "mm",
            box=(x + 24, cy - radius, x + 24 + radius * 2, cy + radius),
        )
        face = fit_font("bold", name, w - radius * 2 - 72, max(16, int(h * 0.048)), 13)
        art.text((x + 40 + radius * 2, cy), name, face, INK, "lm", box=inner)
    cap = font("regular", max(13, int(h * 0.038)))
    art.text((x + 24, y + h - int(h * 0.065)), "Renamed and grouped", cap, MUTED, "lt", box=inner)


def cover_followup(w, h):
    art = Art(w, h, PAPER)
    hairline(art)
    kicker(art, int(h * 0.055))
    margin = int(w * 0.05)
    title = fit_font("bold", "Follow-Up List", int(w * 0.9), max(48, int(h * 0.09)))
    art.text((margin, int(h * 0.155)), "Follow-Up List", title, INK, "lt", box=(margin, int(h * 0.15), w - margin, int(h * 0.25)))
    sub = font("bold", max(22, int(h * 0.038)))
    art.text((margin, int(h * 0.255)), "Status sheet", sub, MUTED, "lt", box=(margin, int(h * 0.25), w - margin, int(h * 0.32)))
    top = int(h * 0.33)
    height = int(h * 0.52)
    card(art, margin, top, w - margin * 2 - 6, height)
    rows = [
        ("Cabinet quote", "Waiting", "Confirm the figure"),
        ("Tile allowance", "Missing", "Request the sheet"),
        ("Range hood", "Unclear", "Confirm included scope"),
        ("Electrical extra", "Received", "Filed, no chase"),
    ]
    _status_table(art, margin, top, w - margin * 2 - 6, height, rows, "NEXT STEP")
    footer_line(art, COVER_FOOTER)
    return art


def cover_photo(w, h):
    art = Art(w, h, PAPER)
    hairline(art)
    kicker(art, int(h * 0.05))
    margin = int(w * 0.05)
    title = fit_font("bold", "Exception Report", int(w * 0.9), max(46, int(h * 0.082)))
    art.text((margin, int(h * 0.145)), "Exception Report", title, INK, "lt", box=(margin, int(h * 0.14), w - margin, int(h * 0.23)))
    sub = font("bold", max(20, int(h * 0.034)))
    art.text((margin, int(h * 0.238)), "Missing and unclear shots", sub, MUTED, "lt", box=(margin, int(h * 0.23), w - margin, int(h * 0.30)))
    top = int(h * 0.31)
    height = int(h * 0.52)
    card(art, margin, top, w - margin * 2 - 6, height)
    rows = [
        ("Before", "before-kitchen-01.png", "Present", SAGE, False),
        ("During", "during-demo-02.png", "Present", CLAY, False),
        ("After", "after-cabinets-03.png", "Missing", None, True),
        ("Issue", "issue-outlet-04.png", "Unclear", DUST, True),
        ("Completion", "completion-05.png", "Missing", None, True),
    ]
    _photo_table(art, margin, top, w - margin * 2 - 6, height, rows)
    footer_line(art, COVER_FOOTER)
    return art


def _status_table(art: Art, x, y, w, h, rows, next_header):
    pad = int(w * 0.04)
    header_h = int(h * 0.16)
    art.draw.rectangle((x, y, x + w, y + header_h), fill=MIST)
    head = font("bold", max(13, int(h * 0.045)))
    cy = y + header_h / 2
    art.text((x + pad, cy), "ITEM", head, PINE, "lm", box=(x + pad, y + 4, x + w * 0.42, y + header_h - 2))
    art.text((x + w * 0.46, cy), "STATUS", head, PINE, "lm", box=(x + w * 0.44, y + 4, x + w * 0.66, y + header_h - 2))
    art.text((x + w * 0.68, cy), next_header, head, PINE, "lm", box=(x + w * 0.68, y + 4, x + w - pad, y + header_h - 2))
    body = h - header_h
    row_h = body / len(rows)
    pill_face = font("bold", max(14, int(row_h * 0.28)))
    labels = [row[1] for row in rows]
    pill_w = max(pill_face.getlength(label) for label in labels) + 32
    colors = {
        "Waiting": (SLATE_FG, SLATE_BG),
        "Missing": (BRICK, BRICK_BG),
        "Unclear": (OCHRE, OCHRE_BG),
        "Received": (PINE, SAGE_BG),
        "Present": (PINE, SAGE_BG),
    }
    item_face_size = max(16, int(row_h * 0.30))
    next_size = max(14, int(row_h * 0.24))
    for index, (item, status, nxt) in enumerate(rows):
        ry = y + header_h + row_h * index
        if index % 2 == 1:
            art.draw.rectangle((x, ry, x + w, ry + row_h), fill=(251, 249, 245))
        mid = ry + row_h / 2
        item_box = (x + pad, ry + 4, x + w * 0.42, ry + row_h - 4)
        item_face = fit_font("bold", item, item_box[2] - item_box[0], item_face_size, 13)
        art.text((x + pad, mid), item, item_face, INK, "lm", box=item_box)
        fg, bg = colors[status]
        pill(art, x + w * 0.64, mid, status, fg, bg, pill_face, pill_w, bounds=(x + 8, y + header_h, x + w - 8, y + h - 8))
        next_box = (x + w * 0.68, ry + 4, x + w - pad, ry + row_h - 4)
        next_face = fit_font("regular", nxt, next_box[2] - next_box[0], next_size, 12)
        art.text((x + w * 0.68, mid), nxt, next_face, INK, "lm", box=next_box)
        if index:
            art.draw.line((x + pad, ry, x + w - pad, ry), fill=LINE, width=1)


def _photo_table(art: Art, x, y, w, h, rows):
    pad = int(w * 0.035)
    header_h = int(h * 0.12)
    art.draw.rectangle((x, y, x + w, y + header_h), fill=MIST)
    head = font("bold", max(13, int(header_h * 0.36)))
    art.text((x + pad, y + header_h / 2), "SLOT AND FILE", head, PINE, "lm", box=(x + pad, y + 4, x + w * 0.62, y + header_h - 2))
    art.text((x + w - pad, y + header_h / 2), "FLAG", head, PINE, "rm", box=(x + w * 0.7, y + 4, x + w - pad, y + header_h - 2))
    body = h - header_h
    row_h = body / len(rows)
    swatch = int(min(row_h * 0.62, w * 0.08))
    pill_face = font("bold", max(13, int(row_h * 0.24)))
    labels = [row[2] for row in rows]
    pill_w = max(pill_face.getlength(label) for label in labels) + 28
    colors = {"Present": (PINE, SAGE_BG), "Missing": (BRICK, BRICK_BG), "Unclear": (OCHRE, OCHRE_BG)}
    for index, (slot, filename, status, block, flagged) in enumerate(rows):
        ry = y + header_h + row_h * index
        mid = ry + row_h / 2
        sx = x + pad
        sy = mid - swatch / 2
        if block is None:
            art.draw.rounded_rectangle(
                (sx, sy, sx + swatch, sy + swatch),
                radius=8,
                outline=LINE,
                width=2,
            )
            art.texts.append("no file")
            dash = font("bold", max(12, swatch // 5))
            art.text((sx + swatch / 2, mid), "—", dash, MUTED, "mm", box=(sx + 2, sy + 2, sx + swatch - 2, sy + swatch - 2))
        else:
            rounded(art, (sx, sy, sx + swatch, sy + swatch), 8, block)
        text_x = sx + swatch + int(w * 0.02)
        box = int(min(22, row_h * 0.28))
        pill_right = x + w - pad
        text_right = pill_right - pill_w - box - 20
        text_box = (text_x, ry + 4, text_right, ry + row_h - 4)
        slot_face = fit_font("bold", slot, text_box[2] - text_box[0], max(16, int(row_h * 0.28)), 13)
        file_face = fit_font("mono", filename, text_box[2] - text_box[0], max(13, int(row_h * 0.20)), 11)
        art.text((text_x, mid - row_h * 0.16), slot, slot_face, INK, "lm", box=text_box)
        art.text((text_x, mid + row_h * 0.18), filename, file_face, MUTED, "lm", box=text_box)
        pill(art, pill_right, mid, status, *colors[status], pill_face, pill_w, bounds=(x + 8, y + header_h, x + w - 8, y + h - 8))
        checkbox(art, pill_right - pill_w - box - 12, mid - box / 2, box, flagged)
        if index:
            art.draw.line((x + pad, ry, x + w - pad, ry), fill=LINE, width=1)


def cover_process(w, h):
    art = Art(w, h, PAPER)
    hairline(art)
    kicker(art, int(h * 0.055))
    margin = int(w * 0.05)
    title = fit_font("bold", "Receive, Organize, Return", int(w * 0.9), max(36, int(h * 0.075)))
    title_top = int(h * 0.18)
    art.text((w / 2, title_top), "Receive, Organize, Return", title, INK, "mt", box=(margin, title_top - 4, w - margin, title_top + title.size + 8))
    sub = font("bold", max(18, int(h * 0.032)))
    sub_top = title_top + title.size + int(h * 0.02)
    art.text((w / 2, sub_top), "One fictional job", sub, MUTED, "mt", box=(margin, sub_top - 2, w - margin, sub_top + sub.size + 6))

    gap = int(w * 0.03)
    top = int(h * 0.36)
    height = int(h * 0.50)
    col_w = (w - margin * 2 - gap * 2) // 3
    steps = [
        ("1", "Receive", _draw_pile),
        ("2", "Organize", _draw_folders),
        ("3", "Return", _draw_packet),
    ]
    for index, (number, label, drawer) in enumerate(steps):
        x = margin + index * (col_w + gap)
        card(art, x, top, col_w, height, radius=18)
        radius = int(min(col_w, height) * 0.11)
        cx = x + col_w / 2
        cy = top + int(height * 0.16)
        art.draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=PINE)
        num = fit_font("bold", number, radius * 1.2, max(18, int(radius * 0.85)))
        art.text((cx, cy), number, num, WHITE, "mm", box=(cx - radius + 2, cy - radius + 2, cx + radius - 2, cy + radius - 2))
        face = fit_font("bold", label, col_w - 24, max(20, int(h * 0.04)))
        label_y = cy + radius + int(height * 0.08)
        art.text((cx, label_y), label, face, INK, "mt", box=(x + 12, label_y - 2, x + col_w - 12, label_y + face.size + 6))
        box = (
            x + int(col_w * 0.12),
            top + int(height * 0.42),
            int(col_w * 0.76),
            int(height * 0.46),
        )
        drawer(art, box)
        if index < 2:
            ax = x + col_w + 4
            ay = top + height * 0.55
            art.draw.line((ax, ay, ax + gap - 10, ay), fill=BRASS, width=3)
            tip = ax + gap - 8
            art.draw.polygon([(tip - 10, ay - 6), (tip, ay), (tip - 10, ay + 6)], fill=BRASS)
    footer_line(art, COVER_FOOTER)
    return art


def _draw_pile(art: Art, box):
    x, y, w, h = box
    slips = (
        (0.10, 0.08, 0.72, 0.62, (236, 230, 220)),
        (0.20, 0.20, 0.72, 0.62, (250, 246, 238)),
        (0.04, 0.34, 0.78, 0.62, WHITE),
    )
    for ox, oy, ow, oh, fill in slips:
        rounded(
            art,
            (x + w * ox, y + h * oy, x + w * ox + w * ow, y + h * oy + h * oh),
            6,
            fill,
            LINE,
            1,
        )
    face = font("mono", max(10, int(w * 0.055)))
    slip = (x + w * 0.06, y + h * 0.36, x + w * 0.78, y + h * 0.96)
    lx = slip[0] + 6
    ly = slip[1] + 6
    for line in ("v7.pdf", "IMG.jpg", "scan.pdf"):
        art.text((lx, ly), line, face, MUTED, "lt", box=slip)
        ly += face.size + 2


def _draw_folders(art: Art, box):
    x, y, w, h = box
    labels = ("01", "02", "03")
    gap = w * 0.06
    fw = (w - gap * 2) / 3
    for index, label in enumerate(labels):
        fx = x + index * (fw + gap)
        fy = y + h * 0.18
        fh = h * 0.70
        tab_w = fw * 0.62
        tab_h = fh * 0.22
        art.draw.rounded_rectangle((fx, fy, fx + tab_w, fy + tab_h + 8), radius=5, fill=PINE)
        art.draw.rounded_rectangle((fx, fy + tab_h, fx + fw, fy + fh), radius=6, fill=SAGE if index == 1 else PINE)
        face = fit_font("bold", label, fw * 0.7, max(12, int(fw * 0.26)))
        art.text(
            (fx + fw / 2, fy + tab_h + (fh - tab_h) / 2),
            label,
            face,
            WHITE,
            "mm",
            box=(fx + 2, fy + tab_h, fx + fw - 2, fy + fh - 2),
        )


def _draw_packet(art: Art, box):
    x, y, w, h = box
    rounded(art, (x, y + h * 0.08, x + w * 0.78, y + h * 0.92), 6, WHITE, LINE, 2)
    art.draw.rectangle((x, y + h * 0.08, x + w * 0.78, y + h * 0.22), fill=PINE)
    face = font("bold", max(10, int(w * 0.07)))
    art.text(
        (x + w * 0.06, y + h * 0.15),
        "Packet",
        face,
        WHITE,
        "lm",
        box=(x + 2, y + h * 0.08, x + w * 0.5, y + h * 0.24),
    )
    line_y = y + h * 0.32
    for _ in range(4):
        art.draw.rectangle((x + w * 0.08, line_y, x + w * 0.68, line_y + max(3, int(h * 0.035))), fill=LINE)
        line_y += h * 0.12
    lx = x + w * 0.52
    rounded(art, (lx, y, lx + w * 0.46, y + h * 0.42), 6, MIST, PINE, 2)
    small = fit_font("bold", "List", w * 0.32, max(11, int(w * 0.09)))
    art.text((lx + w * 0.23, y + h * 0.21), "List", small, PINE, "mm", box=(lx + 4, y + 4, lx + w * 0.46 - 4, y + h * 0.42 - 4))


def rl(rgb, alpha=1):
    return Color(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, alpha=alpha)


def register_pdf_fonts():
    pdfmetrics.registerFont(TTFont("Sans", str(FONT_DIR / "LiberationSans-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Sans-Bold", str(FONT_DIR / "LiberationSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("Mono", str(FONT_DIR / "LiberationMono-Regular.ttf")))


class RecordingCanvas(canvas.Canvas):
    """Canvas that records each string against the box it must stay inside."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.placements: list[tuple[str, tuple, tuple]] = []
        page = self._pagesize
        self.limit = (0, 0, page[0], page[1])
        self.tracking = True

    def _record(self, text, x, y, align):
        if not self.tracking or not text:
            return
        face = pdfmetrics.getFont(self._fontname).face
        size = self._fontsize
        width = pdfmetrics.stringWidth(text, self._fontname, size)
        ascent = face.ascent * size / 1000.0
        descent = abs(face.descent) * size / 1000.0
        if align == "left":
            left = x
        elif align == "right":
            left = x - width
        else:
            left = x - width / 2.0
        bbox = (left, y - descent, left + width, y + ascent)
        self.placements.append((text, bbox, tuple(self.limit)))

    def drawString(self, x, y, text, mode=None, charSpace=0, direction=None, wordSpace=None, shaping=False):
        self._record(text, x, y, "left")
        super().drawString(x, y, text, mode, charSpace, direction, wordSpace, shaping)

    def drawRightString(self, x, y, text, mode=None, charSpace=0, direction=None, wordSpace=None, shaping=False):
        self._record(text, x, y, "right")
        super().drawRightString(x, y, text, mode, charSpace, direction, wordSpace, shaping)

    def drawCentredString(self, x, y, text, mode=None, charSpace=0, direction=None, wordSpace=None, shaping=False):
        self._record(text, x, y, "centre")
        super().drawCentredString(x, y, text, mode, charSpace, direction, wordSpace, shaping)


class Doc:
    def __init__(self, path: Path, title: str):
        self.path = path
        self.texts: list[str] = [title, "North Pine Demo Builders", FOOTER, "Fictional data", "SAMPLE"]
        self.page_w, self.page_h = letter
        self.c = RecordingCanvas(str(path), pagesize=letter, invariant=1)
        self.body_box = (44, 50, self.page_w - 44, self.page_h - 42)
        self.c.setTitle(title)
        self.c.setAuthor("North Pine Demo Builders")
        self.c.setSubject("Fictional sample. Not a real client.")
        self.c.setCreator("sample generator")
        self.c.setKeywords("SAMPLE, fictional data")

    def say(self, value: str):
        if value:
            self.texts.append(value)

    def chrome(self, page: int, pages: int = 3):
        c = self.c
        c.tracking = False
        c.setFillColor(rl(PINE, 0.07))
        c.saveState()
        c.translate(self.page_w / 2, self.page_h / 2)
        c.rotate(32)
        c.setFont("Sans-Bold", 78)
        c.drawCentredString(0, 0, "SAMPLE")
        c.restoreState()
        c.tracking = True
        c.setFillColor(rl(PINE))
        c.rect(0, self.page_h - 34, self.page_w, 34, fill=1, stroke=0)
        c.setFillColor(white)
        c.setFont("Sans-Bold", 11)
        c.limit = (40, self.page_h - 32, self.page_w - 40, self.page_h - 4)
        c.drawString(48, self.page_h - 22, "SAMPLE")
        c.drawRightString(self.page_w - 48, self.page_h - 22, "Fictional data")
        c.setFillColor(rl(LINE))
        c.rect(48, 42, self.page_w - 96, 0.8, fill=1, stroke=0)
        c.setFillColor(rl(MUTED))
        c.setFont("Sans", 8.5)
        c.limit = (40, 16, self.page_w - 40, 38)
        c.drawString(48, 26, FOOTER)
        c.drawRightString(self.page_w - 48, 26, f"{page} / {pages}")
        c.limit = self.body_box
        self.say(FOOTER)
        self.say("SAMPLE")
        self.say("Fictional data")
        self.say(f"{page} / {pages}")

    def wrap(self, text, face, size, width):
        words: list[str] = []
        for word in text.split():
            if pdfmetrics.stringWidth(word, face, size) <= width:
                words.append(word)
                continue
            piece = ""
            for char in word:
                trial = piece + char
                if piece and pdfmetrics.stringWidth(trial, face, size) > width:
                    words.append(piece)
                    piece = char
                else:
                    piece = trial
            if piece:
                words.append(piece)
        lines: list[str] = []
        current = ""
        for word in words:
            trial = word if not current else f"{current} {word}"
            if pdfmetrics.stringWidth(trial, face, size) <= width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [""]

    def paragraph(self, text, x, y, width, face="Sans", size=10.5, leading=15, color=INK):
        c = self.c
        c.setFillColor(rl(color))
        c.setFont(face, size)
        c.limit = (x, 50, x + width, self.page_h - 42)
        baseline = y - size
        for line in self.wrap(text, face, size, width):
            c.drawString(x, baseline, line)
            self.say(line)
            baseline -= leading
        c.limit = self.body_box
        return baseline + leading - 4

    def save(self):
        self.c.save()


def section_title(doc: Doc, text, y):
    doc.c.setFillColor(rl(PINE))
    doc.c.setFont("Sans-Bold", 20)
    doc.c.limit = (48, y - 36, doc.page_w - 48, y)
    doc.c.drawString(48, y - 20, text)
    doc.c.limit = doc.body_box
    doc.say(text)
    doc.c.setFillColor(rl(BRASS))
    doc.c.rect(48, y - 30, 72, 2.5, fill=1, stroke=0)
    return y - 46


def meta_table(doc: Doc, y, rows):
    width = doc.page_w - 96
    row_h = 22
    height = row_h * len(rows) + 8
    bottom = y - height
    doc.c.setFillColor(white)
    doc.c.roundRect(48, bottom, width, height, 6, fill=1, stroke=0)
    doc.c.setStrokeColor(rl(LINE))
    cursor = y - 20
    for label, value in rows:
        doc.c.setFillColor(rl(MUTED))
        doc.c.setFont("Sans-Bold", 9)
        doc.c.limit = (62, cursor - 3, 168, cursor + 11)
        doc.c.drawString(62, cursor, label)
        doc.say(label)
        doc.c.setFillColor(rl(INK))
        doc.c.setFont("Sans", 10)
        doc.c.limit = (176, cursor - 3, doc.page_w - 56, cursor + 11)
        doc.c.drawString(176, cursor, value)
        doc.say(value)
        doc.c.limit = doc.body_box
        cursor -= row_h
    return bottom - 16


def data_table(doc: Doc, y, columns, rows, font_size=9, min_row=22):
    """Draw a header-plus-body table. columns is (title, width). y is the top."""
    x0 = 48
    header_h = 22
    doc.c.setFillColor(rl(MIST))
    total_w = sum(width for _, width in columns)
    doc.c.rect(x0, y - header_h, total_w, header_h, fill=1, stroke=0)
    doc.c.setFillColor(rl(PINE))
    doc.c.setFont("Sans-Bold", 8)
    x = x0
    for title, width in columns:
        doc.c.limit = (x + 4, y - header_h + 2, x + width - 4, y - 2)
        doc.c.drawString(x + 6, y - 15, title)
        doc.say(title)
        x += width
    doc.c.limit = doc.body_box
    cursor = y - header_h
    for index, row in enumerate(rows):
        heights = []
        wrapped = []
        for value, (_, width) in zip(row, columns):
            lines = doc.wrap(str(value), "Sans", font_size, width - 12)
            wrapped.append(lines)
            heights.append(max(min_row, 8 + len(lines) * (font_size + 3)))
        row_h = max(heights)
        if index % 2 == 0:
            doc.c.setFillColor(white)
        else:
            doc.c.setFillColor(rl((251, 249, 245)))
        doc.c.rect(x0, cursor - row_h, total_w, row_h, fill=1, stroke=0)
        doc.c.setStrokeColor(rl(LINE))
        doc.c.line(x0, cursor, x0 + total_w, cursor)
        x = x0
        for lines, (_, width) in zip(wrapped, columns):
            doc.c.setFillColor(rl(INK))
            doc.c.setFont("Sans", font_size)
            doc.c.limit = (x + 4, cursor - row_h + 2, x + width - 4, cursor - 2)
            text_y = cursor - font_size - 5
            for line in lines:
                doc.c.drawString(x + 6, text_y, line)
                doc.say(line)
                text_y -= font_size + 3
            x += width
        doc.c.limit = doc.body_box
        cursor -= row_h
    doc.c.setStrokeColor(rl(LINE))
    doc.c.line(x0, cursor, x0 + total_w, cursor)
    return cursor - 14


def note_box(doc: Doc, y, text, width=None):
    width = width or (doc.page_w - 96)
    lines = doc.wrap(text, "Sans", 9.5, width - 24)
    height = 16 + len(lines) * 13
    bottom = y - height
    doc.c.setFillColor(rl(OCHRE_BG))
    doc.c.roundRect(48, bottom, width, height, 6, fill=1, stroke=0)
    doc.c.setFillColor(rl(BRASS))
    doc.c.rect(48, bottom, 4, height, fill=1, stroke=0)
    doc.c.setFillColor(rl(INK))
    doc.c.setFont("Sans", 9.5)
    doc.c.limit = (64, bottom + 4, 64 + (width - 24), y - 4)
    baseline = y - 16
    for line in lines:
        doc.c.drawString(64, baseline, line)
        doc.say(line)
        baseline -= 13
    doc.c.limit = doc.body_box
    return bottom - 14


def build_quote_pdf(path: Path):
    doc = Doc(path, "SAMPLE Quote Packet — fictional data")
    doc.chrome(1)
    y = doc.page_h - 58
    doc.c.setFillColor(rl(MUTED))
    doc.c.setFont("Sans-Bold", 9)
    doc.c.drawString(48, y, "NORTH PINE DEMO BUILDERS")
    doc.say("NORTH PINE DEMO BUILDERS")
    y = section_title(doc, "Quote packet", y - 18)
    doc.c.setFillColor(rl(MUTED))
    doc.c.setFont("Sans", 11)
    dek = "Job NP-1042  ·  kitchen remodel  ·  fictional job site"
    doc.c.drawString(48, y, dek)
    doc.say(dek)
    y -= 22
    y = meta_table(
        doc,
        y,
        [
            ("Document", "Sample quote packet"),
            ("Job", "NP-1042 kitchen remodel"),
            ("Site", "Fictional job site. No postal address."),
            ("Files shown", "12 fictional files. A trial pile can hold up to 20."),
            ("Figures", "Copied from the fictional source files. Blank means not stated."),
            ("Date label", "14 Apr 2026, fictional label only."),
        ],
    )
    y = doc.paragraph(
        "This sample shows one job's quote and estimate files renamed, grouped, and listed. "
        "It is a fictional packet for review. It is not a client file.",
        48,
        y,
        doc.page_w - 96,
    )
    y -= 8
    y = doc.paragraph("Inside this sample", 48, y, doc.page_w - 96, "Sans-Bold", 12, 16, PINE)
    for line in (
        "1.  This cover and a short contents note.",
        "2.  A file index: the messy name beside the packet name.",
        "3.  Figures that were actually written in the source files, plus a follow-up list.",
    ):
        y = doc.paragraph(line, 48, y, doc.page_w - 96, "Sans", 10.5, 15)
        y += 2
    y -= 8
    note_box(
        doc,
        y,
        "Missing amounts stay blank. This sample does not fill in a price, a measurement, or a promise. "
        "Follow-up lines are drafts for the contractor to review. Nothing in this file was sent onward.",
    )
    doc.c.showPage()

    doc.chrome(2)
    y = section_title(doc, "File index", doc.page_h - 58)
    y = doc.paragraph(
        "The first column is the invented messy name. The second column is the organized packet name. "
        "The third column is the folder group.",
        48,
        y,
        doc.page_w - 96,
        "Sans",
        10,
        14,
    )
    y -= 6
    columns = [("Original name", 175), ("Packet name", 230), ("Group", 111)]
    rows = [
        ("IMG_4481.jpg", "04-photos/before-kitchen-01.jpg", "04 Photos"),
        ("quote FINAL v7.pdf", "02-quotes/cabinet-quote.pdf", "02 Quotes"),
        ("scan (3).pdf", "01-received/supplier-note.pdf", "01 Received"),
        ("homeowner thread.pdf", "01-received/homeowner-thread.pdf", "01 Received"),
        ("site notes.docx", "03-notes/site-notes.pdf", "03 Notes"),
        ("bid sheet (2).xlsx", "02-quotes/electrical-extra.pdf", "02 Quotes"),
        ("hood variation.pdf", "02-quotes/range-hood-variation.pdf", "02 Quotes"),
        ("IMG_4490.jpg", "04-photos/during-demo-02.jpg", "04 Photos"),
        ("IMG_4502.jpg", "04-photos/walkthrough-06.jpg", "04 Photos"),
        ("outlet maybe.jpg", "04-photos/issue-outlet-04.jpg", "04 Photos"),
        ("(no file in the pile)", "01-received/tile-allowance-not-in-pile.txt", "01 Received"),
        ("plumber note.pdf", "01-received/plumber-note.pdf", "01 Received"),
    ]
    y = data_table(doc, y, columns, rows, font_size=8.5, min_row=24)
    note_box(
        doc,
        y,
        "The tile allowance row is a stand-in name because that sheet was not in the pile. "
        "The sample does not invent the missing sheet.",
    )
    doc.c.showPage()

    doc.chrome(3)
    y = section_title(doc, "Stated figures and follow-up", doc.page_h - 58)
    y = doc.paragraph(
        "Amounts are copied from fictional source files and labeled USD as written. "
        "No tax is added. No currency is converted. A blank is not a zero.",
        48,
        y,
        doc.page_w - 96,
        "Sans",
        10,
        14,
    )
    y -= 4
    figure_cols = [("Line", 150), ("Source file", 145), ("Qty", 40), ("Unit USD", 90), ("Line USD", 91)]
    figure_rows = [
        ("Cabinets", "cabinet-quote.pdf", "1", money(CABINET), money(CABINET)),
        ("Electrical extra", "electrical-extra.pdf", "1", money(ELECTRICAL), money(ELECTRICAL)),
        ("Range hood variation", "range-hood-variation.pdf", "1", "not stated", "not stated"),
        ("Tile allowance", "not in the pile", "—", "not stated", "not stated"),
    ]
    y = data_table(doc, y, figure_cols, figure_rows, font_size=9, min_row=22)
    subtotal = f"Subtotal of stated lines only: {money(SUBTOTAL)} USD. This is not a job total."
    y = doc.paragraph(subtotal, 48, y, doc.page_w - 96, "Sans-Bold", 10.5, 14, PINE)
    y -= 8
    y = doc.paragraph("Follow-up list", 48, y, doc.page_w - 96, "Sans-Bold", 13, 16, PINE)
    y -= 2
    follow_cols = [("Item", 120), ("Status", 78), ("Draft for review", 318)]
    follow_rows = [
        ("Tile allowance", "Missing", "Please send the tile allowance sheet so it can sit with this packet."),
        ("Range hood variation", "Unclear", "The file does not state a figure or what is included. Please confirm."),
        ("Cabinet quote", "Waiting", "Please confirm this is the cabinet figure to file."),
        ("Electrical extra", "Received", "Filed under 02 Quotes. No chase written."),
        ("Plumber note", "Received", "Filed. The note does not state a figure."),
    ]
    y = data_table(doc, y, follow_cols, follow_rows, font_size=8.5, min_row=28)
    note_box(
        doc,
        y,
        "Draft wording stays in this packet until the contractor reviews it. The sample does not contact anyone.",
    )
    doc.save()
    return doc.texts, doc.c.placements


def build_photo_pdf(path: Path):
    doc = Doc(path, "SAMPLE Photo Exception Report — fictional data")
    doc.chrome(1)
    y = doc.page_h - 58
    doc.c.setFillColor(rl(MUTED))
    doc.c.setFont("Sans-Bold", 9)
    doc.c.drawString(48, y, "NORTH PINE DEMO BUILDERS")
    doc.say("NORTH PINE DEMO BUILDERS")
    y = section_title(doc, "Photo exception report", y - 18)
    dek = "Job NP-1042  ·  kitchen remodel  ·  fictional job site"
    doc.c.setFillColor(rl(MUTED))
    doc.c.setFont("Sans", 11)
    doc.c.drawString(48, y, dek)
    doc.say(dek)
    y -= 20
    y = doc.paragraph(
        "This sample checks a six-slot punch list against filenames. Solid color blocks stand in for photographs. "
        "No house picture is used.",
        48,
        y,
        doc.page_w - 96,
    )
    y -= 6
    y = meta_table(
        doc,
        y,
        [
            ("Document", "Sample photo closeout exception report"),
            ("Job", "NP-1042 kitchen remodel"),
            ("Site", "Fictional job site. No postal address."),
            ("Check", "File name present, missing, or unclear."),
            ("Date label", "14 Apr 2026, fictional label only."),
        ],
    )
    y = doc.paragraph("What a finding means", 48, y, doc.page_w - 96, "Sans-Bold", 12, 16, PINE)
    for line in (
        "Present — a fictional file name is on the list for that slot.",
        "Missing — the slot has no file.",
        "Unclear — a file name is listed, and this sample does not treat it as a clear shot.",
    ):
        y = doc.paragraph(line, 48, y, doc.page_w - 96, "Sans", 10.5, 15)
        y += 2
    y -= 6
    y = doc.paragraph("What this sample does not do", 48, y, doc.page_w - 96, "Sans-Bold", 12, 16, PINE)
    y = doc.paragraph(
        "It does not score workmanship, safety, or cleanliness. It does not approve an invoice. "
        "It does not say the job is finished.",
        48,
        y,
        doc.page_w - 96,
    )
    y -= 4
    note_box(
        doc,
        y,
        "Slots on the list: Before, During, After, Issue, Completion, Walkthrough. "
        "Page 2 uses a color block and a filename in place of a photograph.",
    )
    doc.c.showPage()

    doc.chrome(2)
    y = section_title(doc, "File slots", doc.page_h - 58)
    y = doc.paragraph(
        "Each block is a flat color plus a filename. The color is not a photograph.",
        48,
        y,
        doc.page_w - 96,
        "Sans",
        10.5,
        14,
    )
    y -= 8
    slots = [
        ("Before", "before-kitchen-01.png", "Present", SAGE),
        ("During", "during-demo-02.png", "Present", CLAY),
        ("After", "Expected: after-cabinets-03.png", "Missing", None),
        ("Issue", "issue-outlet-04.png", "Unclear", DUST),
        ("Completion", "Expected: completion-05.png", "Missing", None),
        ("Walkthrough", "walkthrough-06.png", "Present", SLATE),
    ]
    grid_bottom = draw_slot_grid(doc, y, slots)
    note_box(
        doc,
        grid_bottom,
        "Empty blocks are slots with no file. A dust-colored block is the unclear file: the name is known, the shot is not treated as clear.",
    )
    doc.c.showPage()

    doc.chrome(3)
    y = section_title(doc, "Exception list", doc.page_h - 58)
    y = doc.paragraph(
        "Flags mark missing or unclear files only. A flag is not a quality score.",
        48,
        y,
        doc.page_w - 96,
    )
    y -= 6
    cols = [("Slot", 100), ("Filename", 190), ("Finding", 90), ("Flag", 136)]
    rows = [
        ("Before", "before-kitchen-01.png", "Present", "—"),
        ("During", "during-demo-02.png", "Present", "—"),
        ("After", "Expected: after-cabinets-03.png", "Missing", "Flagged"),
        ("Issue", "issue-outlet-04.png", "Unclear", "Flagged"),
        ("Completion", "Expected: completion-05.png", "Missing", "Flagged"),
        ("Walkthrough", "walkthrough-06.png", "Present", "—"),
    ]
    y = data_table(doc, y, cols, rows, font_size=10, min_row=28)
    y = doc.paragraph(
        "Count in this sample: Present 3, Missing 2, Unclear 1.",
        48,
        y,
        doc.page_w - 96,
        "Sans-Bold",
        11,
        15,
        PINE,
    )
    y -= 6
    note_box(
        doc,
        y,
        "A flagged slot needs a file, or a file a person can read as that slot. "
        "The flag does not score the work and does not approve a payment.",
    )
    doc.save()
    return doc.texts, doc.c.placements


def draw_slot_grid(doc: Doc, top, slots):
    cols = 2
    gap_x = 16
    gap_y = 12
    width = (doc.page_w - 96 - gap_x) / cols
    height = 118
    for index, (slot, filename, finding, color) in enumerate(slots):
        col = index % cols
        row = index // cols
        x = 48 + col * (width + gap_x)
        y_top = top - row * (height + gap_y)
        bottom = y_top - height
        doc.c.setFillColor(white)
        doc.c.roundRect(x, bottom, width, height, 6, fill=1, stroke=0)
        block_h = 48
        block_y = bottom + height - 14 - block_h
        if color is None:
            doc.c.setStrokeColor(rl(LINE))
            doc.c.setDash(2, 2)
            doc.c.setFillColor(rl(EMPTY))
            doc.c.roundRect(x + 12, block_y, width - 24, block_h, 4, fill=1, stroke=1)
            doc.c.setDash()
            doc.c.setFillColor(rl(MUTED))
            doc.c.setFont("Sans-Bold", 9)
            doc.c.limit = (x + 16, block_y + 4, x + width - 16, block_y + block_h - 4)
            doc.c.drawCentredString(x + width / 2, block_y + 19, "No file")
            doc.say("No file")
        else:
            doc.c.setFillColor(rl(color))
            doc.c.roundRect(x + 12, block_y, width - 24, block_h, 4, fill=1, stroke=0)
        doc.c.setFillColor(rl(INK))
        doc.c.setFont("Sans-Bold", 10)
        doc.c.limit = (x + 12, bottom + 28, x + width - 12, bottom + 48)
        doc.c.drawString(x + 12, bottom + 36, f"{slot}  ·  {finding}")
        doc.say(f"{slot}  ·  {finding}")
        doc.c.setFillColor(rl(MUTED))
        doc.c.setFont("Mono", 8)
        doc.c.limit = (x + 12, bottom + 8, x + width - 12, bottom + 32)
        doc.c.drawString(x + 12, bottom + 20, filename)
        doc.say(filename)
        doc.c.limit = doc.body_box
    rows = (len(slots) + cols - 1) // cols
    return top - rows * (height + gap_y) + gap_y - 8


def generate(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    images = {
        "cf-r3_fiverr-cover-packet_1280x769_v1.png": (cover_packet, (1280, 769)),
        "cf-r3_fiverr-cover-followup_1280x769_v1.png": (cover_followup, (1280, 769)),
        "cf-r3_fiverr-cover-photo_1280x769_v1.png": (cover_photo, (1280, 769)),
        "cf-r3_upwork-catalog-packet_1000x750_v1.png": (cover_packet, (1000, 750)),
        "cf-r3_upwork-catalog-followup_1000x750_v1.png": (cover_followup, (1000, 750)),
        "cf-r3_upwork-catalog-photo_1000x750_v1.png": (cover_photo, (1000, 750)),
        "cf-r3_upwork-catalog-process_1000x750_v1.png": (cover_process, (1000, 750)),
    }
    drawn: dict[Path, tuple[list[str], list]] = {}
    for name, (builder, size) in images.items():
        art = builder(*size)
        path = out / name
        art.save(path)
        drawn[path] = (list(art.texts), art.placements)
    register_pdf_fonts()
    quote = out / "cf-r3_sample-quote-packet_FICTIONAL_v1.pdf"
    photo = out / "cf-r3_sample-photo-exception_FICTIONAL_v1.pdf"
    drawn[quote] = build_quote_pdf(quote)
    drawn[photo] = build_photo_pdf(photo)
    return drawn


def _placement_errors(placements) -> list[str]:
    found = []
    for value, bbox, limit in placements:
        if outside(bbox, limit):
            snippet = value if len(value) <= 48 else value[:45] + "..."
            found.append(
                f"{snippet!r} bbox {tuple(round(v, 1) for v in bbox)} outside {tuple(round(v, 1) for v in limit)}"
            )
    return found


def _blob(path: Path, recorded: list[str]) -> str:
    parts = list(recorded)
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        info = reader.metadata
        if info:
            for value in info.values():
                parts.append(str(value))
        for page in reader.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _detector_catches_overflow() -> None:
    """The box check has to fail closed. A string drawn past its box must be reported."""
    art = Art(70, 36, PAPER)
    art.text((58, 6), "OVERFLOW", font("bold", 20), INK, "lt", box=(0, 0, 70, 36))
    if not art.overflows():
        raise SystemExit("text-box check did not flag a string drawn past its box")
    inside = Art(220, 48, PAPER)
    inside.text((12, 12), "Fits", font("bold", 18), INK, "lt", box=(0, 0, 220, 48))
    if inside.overflows():
        raise SystemExit("text-box check flagged a string that fits: " + "; ".join(inside.overflows()))


def check(drawn: dict[Path, tuple[list[str], list]]):
    errors: list[str] = []
    expected_png = {
        "cf-r3_fiverr-cover-packet_1280x769_v1.png": (1280, 769),
        "cf-r3_fiverr-cover-followup_1280x769_v1.png": (1280, 769),
        "cf-r3_fiverr-cover-photo_1280x769_v1.png": (1280, 769),
        "cf-r3_upwork-catalog-packet_1000x750_v1.png": (1000, 750),
        "cf-r3_upwork-catalog-followup_1000x750_v1.png": (1000, 750),
        "cf-r3_upwork-catalog-photo_1000x750_v1.png": (1000, 750),
        "cf-r3_upwork-catalog-process_1000x750_v1.png": (1000, 750),
    }
    headlines = {
        "packet": "Quote Packet",
        "followup": "Follow-Up List",
        "photo": "Exception Report",
        "process": "Receive, Organize, Return",
    }
    for headline in headlines.values():
        words = re.findall(r"[A-Za-z0-9']+", headline)
        if len(words) > 10:
            errors.append(f"headline over 10 words: {headline}")

    for path, (recorded, placements) in drawn.items():
        for problem in _placement_errors(placements):
            errors.append(f"{path.name} text runs past its box: {problem}")
        blob = _blob(path, recorded).casefold()
        if "sample" not in blob or "fictional data" not in blob:
            errors.append(f"{path.name} is missing SAMPLE or Fictional data")
        if "north pine demo builders" not in blob:
            errors.append(f"{path.name} is missing the fictional company")
        for banned in BANNED:
            if banned in blob:
                errors.append(f"{path.name} contains banned text {banned!r}")
        if PHONE_RE.search(blob):
            errors.append(f"{path.name} matches a phone-number pattern")
        if path.suffix.lower() == ".png":
            with Image.open(path) as image:
                if image.size != expected_png[path.name]:
                    errors.append(f"{path.name} size {image.size}")
                if image.mode != "RGB":
                    errors.append(f"{path.name} mode {image.mode}")
                dpi = image.info.get("dpi")
                if not dpi or any(abs(float(value) - 72) > 0.6 for value in dpi[:2]):
                    errors.append(f"{path.name} dpi {dpi}")
            if path.stat().st_size > 10 * 1024 * 1024:
                errors.append(f"{path.name} exceeds 10 MB")
        else:
            reader = PdfReader(str(path))
            if len(reader.pages) != 3:
                errors.append(f"{path.name} has {len(reader.pages)} pages")
            extracted = "\n".join((page.extract_text() or "") for page in reader.pages)
            if "not a real client" not in extracted.casefold():
                errors.append(f"{path.name} footer missing from extracted text")

    quote = next(path for path in drawn if path.name.startswith("cf-r3_sample-quote-packet"))
    quote_text = "\n".join((page.extract_text() or "") for page in PdfReader(str(quote)).pages)
    for needle in (money(CABINET), money(ELECTRICAL), money(SUBTOTAL), "not stated", "Tile allowance"):
        if needle not in quote_text:
            errors.append(f"quote packet missing {needle}")
    amounts = set(re.findall(r"\d[\d,]*\.\d{2}", quote_text))
    allowed = {money(CABINET), money(ELECTRICAL), money(SUBTOTAL)}
    if amounts != allowed:
        errors.append(f"unexpected money amounts in quote packet: {sorted(amounts)}")

    photo = next(path for path in drawn if path.name.startswith("cf-r3_sample-photo-exception"))
    photo_text = "\n".join((page.extract_text() or "") for page in PdfReader(str(photo)).pages)
    for needle in ("before-kitchen-01.png", "completion-05.png", "workmanship", "not a photograph"):
        if needle not in photo_text:
            errors.append(f"photo report missing {needle}")
    if re.search(r"\d[\d,]*\.\d{2}", photo_text):
        errors.append("photo report contains a money amount")

    if errors:
        raise SystemExit("Sample check failed:\n- " + "\n- ".join(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate fictional SAMPLE marketplace assets.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    missing = [name for name in (
        "LiberationSans-Regular.ttf",
        "LiberationSans-Bold.ttf",
        "LiberationMono-Regular.ttf",
        "OFL.txt",
    ) if not (FONT_DIR / name).is_file()]
    if missing:
        raise SystemExit(f"Missing font files in {FONT_DIR}: {', '.join(missing)}")
    _detector_catches_overflow()
    drawn = generate(args.out)
    check(drawn)
    print(f"{'file':<56} {'px or pages':<16} bytes")
    for path in drawn:
        if path.suffix.lower() == ".png":
            with Image.open(path) as image:
                detail = f"{image.size[0]}x{image.size[1]}"
        else:
            detail = f"{len(PdfReader(str(path)).pages)} pages"
        print(f"{path.name:<56} {detail:<16} {path.stat().st_size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
