"""
KDP-ready book cover generator for Polly Connect.
Generates a full wrap cover PDF (back + spine + front) with bleed.

KDP 6x9 specs (white paper):
- Spine width = page_count × 0.002252 inches
- Bleed = 0.125" on all sides
- Total width = 0.125 + 6 + spine + 6 + 0.125
- Total height = 0.125 + 9 + 0.125 = 9.25"
- Safe zone = 0.25" from trim edge
"""

import io
import json
import logging
import os
from typing import Optional

from reportlab.lib.pagesizes import inch
from reportlab.lib.colors import Color, white, black
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib.utils import ImageReader

logger = logging.getLogger(__name__)

# KDP specs for 6x9 trim, white paper
TRIM_W = 6.0  # inches
TRIM_H = 9.0
BLEED = 0.125
SPINE_PER_PAGE = 0.002252  # white paper (cream = 0.0025)
MIN_SPINE = 0.25  # KDP minimum for spine text
SAFE_ZONE = 0.25  # keep text this far from trim edges


def calculate_spine_width(page_count: int) -> float:
    """Calculate spine width in inches from page count (white paper)."""
    return max(page_count * SPINE_PER_PAGE, 0.04)


def hex_to_color(hex_str: str) -> Color:
    """Convert '#RRGGBB' to ReportLab Color."""
    hex_str = hex_str.lstrip("#")
    if len(hex_str) != 6:
        return black
    r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
    return Color(r / 255, g / 255, b / 255)


# Register custom TTF fonts
_fonts_registered = False

def _register_fonts():
    global _fonts_registered
    if _fonts_registered:
        return
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        fonts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "fonts")
        font_files = {
            "GreatVibes": "GreatVibes-Regular.ttf",
            "PinyonScript": "PinyonScript-Regular.ttf",
            "PlayfairDisplay-Bold": "PlayfairDisplay-Bold.ttf",
            "PlayfairDisplay": "PlayfairDisplay-Regular.ttf",
            "DancingScript": "DancingScript-Regular.ttf",
            "CormorantGaramond-Bold": "CormorantGaramond-Bold.ttf",
            "Lora-Bold": "Lora-Bold.ttf",
            "Lora": "Lora-Regular.ttf",
        }
        for name, filename in font_files.items():
            path = os.path.join(fonts_dir, filename)
            if os.path.exists(path):
                pdfmetrics.registerFont(TTFont(name, path))
        _fonts_registered = True
    except Exception as e:
        logger.warning(f"Custom font registration failed: {e}")


# Font choices — built-ins + custom TTFs
FONT_CHOICES = {
    "Helvetica": "Helvetica",
    "Helvetica-Bold": "Helvetica-Bold",
    "Times-Roman": "Times-Roman",
    "Times-Bold": "Times-Bold",
    "Courier": "Courier",
    "Courier-Bold": "Courier-Bold",
    "GreatVibes": "GreatVibes",
    "PinyonScript": "PinyonScript",
    "DancingScript": "DancingScript",
    "PlayfairDisplay": "PlayfairDisplay",
    "PlayfairDisplay-Bold": "PlayfairDisplay-Bold",
    "CormorantGaramond-Bold": "CormorantGaramond-Bold",
    "Lora-Bold": "Lora-Bold",
    "Lora": "Lora",
}


def generate_cover_pdf(
    page_count: int,
    title: str = "My Legacy",
    subtitle: str = "",
    author_name: str = "",
    blurb: str = "",
    cover_photo_path: Optional[str] = None,
    bg_color: str = "#1a3c5e",
    font_color: str = "#ffffff",
    font_name: str = "Helvetica-Bold",
    spine_text: str = "",
    title_offset: float = 0.0,
    photo_offset: float = 0.0,
    author_offset: float = 0.0,
    blurb_bg_color: str = "#ffffff",
    blurb_offset: float = 0.0,
) -> bytes:
    """
    Generate a KDP-ready full wrap cover PDF.

    Returns PDF bytes.
    """
    _register_fonts()
    spine_w = calculate_spine_width(page_count)
    total_w = (BLEED + TRIM_W + spine_w + TRIM_W + BLEED) * inch
    total_h = (BLEED + TRIM_H + BLEED) * inch

    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=(total_w, total_h))

    bg = hex_to_color(bg_color)
    fg = hex_to_color(font_color)
    font = FONT_CHOICES.get(font_name, "Helvetica-Bold")

    # ── Fill background ──
    c.setFillColor(bg)
    c.rect(0, 0, total_w, total_h, fill=True, stroke=False)

    # ── Coordinate helpers (from trim edges, not bleed) ──
    # Back cover: left trim starts at BLEED
    back_left = BLEED * inch
    back_right = (BLEED + TRIM_W) * inch
    # Spine
    spine_left = back_right
    spine_right = spine_left + spine_w * inch
    # Front cover: right trim
    front_left = spine_right
    front_right = front_left + TRIM_W * inch
    # Vertical
    bottom_trim = BLEED * inch
    top_trim = (BLEED + TRIM_H) * inch

    # ── FRONT COVER ──
    # Layout: Title+Subtitle (top) → Photo (middle, fills available space) → Author (bottom)
    front_cx = front_left + (TRIM_W * inch) / 2
    safe_top = top_trim - SAFE_ZONE * inch
    safe_bottom = bottom_trim + SAFE_ZONE * inch
    max_text_w = (TRIM_W - SAFE_ZONE * 2) * inch
    from reportlab.pdfbase.pdfmetrics import stringWidth

    # ── 1. Measure title + subtitle block ──
    title_font_size = 36
    sub_font_size = 18
    # For subtitle, use non-bold variant if available, else same font
    _bold_to_regular = {
        "Helvetica-Bold": "Helvetica", "Times-Bold": "Times-Roman",
        "Courier-Bold": "Courier", "PlayfairDisplay-Bold": "PlayfairDisplay",
        "CormorantGaramond-Bold": "CormorantGaramond-Bold",
        "Lora-Bold": "Lora",
    }
    sub_font_name = _bold_to_regular.get(font, font)

    title_lines = _wrap_text(title, font, title_font_size, max_text_w)
    title_line_h = title_font_size * 1.3
    title_block_h = len(title_lines) * title_line_h
    sub_gap = 8  # points between title and subtitle
    sub_line_h = sub_font_size * 1.3
    sub_block_h = (sub_line_h + sub_gap) if subtitle else 0
    text_block_h = title_block_h + sub_block_h
    title_padding = 0.3 * inch  # padding above and below text block

    # ── 2. Measure author block ──
    author_font_size = 20
    author_block_h = (author_font_size * 1.3 + 0.2 * inch) if author_name else 0

    # ── 3. Calculate photo zone (everything between title block and author) ──
    text_bottom_y = safe_top - title_padding - text_block_h - title_padding
    author_top_y = safe_bottom + author_block_h
    photo_zone_top = text_bottom_y - 0.1 * inch
    photo_zone_bottom = author_top_y + 0.1 * inch
    photo_zone_h = photo_zone_top - photo_zone_bottom

    # ── 4. Draw title + subtitle (grouped tightly, with user offset) ──
    title_y_offset = title_offset * inch  # positive = up, negative = down
    c.setFillColor(fg)
    c.setFont(font, title_font_size)
    y = safe_top - title_padding - title_y_offset
    for i, line in enumerate(title_lines):
        c.drawCentredString(front_cx, y, line)
        if i < len(title_lines) - 1:
            y -= title_line_h

    if subtitle:
        y -= sub_font_size + sub_gap
        c.setFont(sub_font_name, sub_font_size)
        c.drawCentredString(front_cx, y, subtitle)

    # ── 5. Draw photo (fills middle zone, respects aspect ratio) ──
    if cover_photo_path and os.path.exists(cover_photo_path):
        try:
            img = ImageReader(cover_photo_path)
            iw, ih = img.getSize()
            max_w = max_text_w
            max_h = max(photo_zone_h, 1.0 * inch)  # at least 1 inch
            scale = min(max_w / iw, max_h / ih)
            draw_w = iw * scale
            draw_h = ih * scale
            img_x = front_cx - draw_w / 2
            # Center photo in the photo zone, with user offset
            photo_y_offset = photo_offset * inch
            img_y = photo_zone_bottom + (photo_zone_h - draw_h) / 2 - photo_y_offset
            c.drawImage(img, img_x, img_y, draw_w, draw_h, preserveAspectRatio=True)
        except Exception as e:
            logger.warning(f"Cover photo failed: {e}")

    # ── 6. Draw author name at bottom ──
    if author_name:
        author_y_offset = author_offset * inch
        c.setFillColor(fg)
        c.setFont(font, author_font_size)
        c.drawCentredString(front_cx, safe_bottom + 0.3 * inch + author_y_offset, author_name)

    # ── SPINE ──
    if spine_w >= MIN_SPINE:
        spine_cx = spine_left + (spine_w * inch) / 2
        spine_text_str = spine_text or title
        c.saveState()
        c.setFillColor(fg)
        # Spine text runs bottom to top (rotated 90°)
        c.translate(spine_cx, bottom_trim + (TRIM_H * inch) / 2)
        c.rotate(90)
        spine_font_size = min(12, spine_w * 72 * 0.6)  # 60% of spine width in points
        c.setFont(font, spine_font_size)
        # Truncate if too long for spine
        max_spine_chars = int((TRIM_H - SAFE_ZONE * 2) * 72 / (spine_font_size * 0.6))
        if len(spine_text_str) > max_spine_chars:
            spine_text_str = spine_text_str[:max_spine_chars - 3] + "..."
        c.drawCentredString(0, -spine_font_size / 3, spine_text_str)
        c.restoreState()

    # ── BACK COVER ──
    back_cx = back_left + (TRIM_W * inch) / 2
    back_safe_left = back_left + SAFE_ZONE * inch
    back_safe_right = back_right - SAFE_ZONE * inch
    back_text_width = back_safe_right - back_safe_left

    if blurb:
        # Draw blurb in a colored box — auto-shrink font to fit
        blurb_bg = hex_to_color(blurb_bg_color)
        blurb_font_name = _bold_to_regular.get(font, font)
        # Use Helvetica for blurb if custom font (script fonts hard to read small)
        if blurb_font_name not in ("Helvetica", "Helvetica-Bold", "Times-Roman",
                                    "Times-Bold", "Courier", "Courier-Bold",
                                    "PlayfairDisplay", "PlayfairDisplay-Bold",
                                    "Lora", "Lora-Bold", "CormorantGaramond-Bold"):
            blurb_font_name = "Helvetica"

        blurb_padding_x = 0.4 * inch
        blurb_padding_y = 0.35 * inch
        blurb_box_width = back_text_width
        inner_width = blurb_box_width - blurb_padding_x * 2

        # Max box height: 70% of back cover safe area
        max_box_height = (TRIM_H - SAFE_ZONE * 2) * inch * 0.7

        # Auto-shrink font until box fits
        blurb_size = 12
        while blurb_size >= 8:
            line_height = blurb_size * 1.6
            lines = _wrap_text(blurb, blurb_font_name, blurb_size, inner_width)
            blurb_text_height = len(lines) * line_height
            blurb_box_height = blurb_padding_y + blurb_text_height + blurb_padding_y
            if blurb_box_height <= max_box_height:
                break
            blurb_size -= 0.5

        # Center the box vertically on the back cover, with user offset
        blurb_y_offset = blurb_offset * inch
        back_center_y = bottom_trim + (TRIM_H * inch) / 2
        box_x = back_cx - blurb_box_width / 2
        box_y = back_center_y - blurb_box_height / 2 + blurb_y_offset
        box_top = box_y + blurb_box_height

        # Draw rounded background box
        c.setFillColor(blurb_bg)
        c.roundRect(box_x, box_y, blurb_box_width, blurb_box_height, 10, fill=True, stroke=False)

        # Auto text color based on box brightness
        blurb_r = int(blurb_bg_color.lstrip("#")[0:2], 16) / 255
        blurb_g_val = int(blurb_bg_color.lstrip("#")[2:4], 16) / 255
        blurb_b = int(blurb_bg_color.lstrip("#")[4:6], 16) / 255
        blurb_brightness = (blurb_r * 299 + blurb_g_val * 587 + blurb_b * 114) / 1000
        blurb_text_color = black if blurb_brightness > 0.5 else white

        c.setFillColor(blurb_text_color)
        c.setFont(blurb_font_name, blurb_size)
        # Draw from top of box, centered vertically in the box
        text_start_y = box_top - blurb_padding_y
        y = text_start_y
        for line in lines:
            c.drawCentredString(back_cx, y, line)
            y -= line_height

    # Polly Connect branding at bottom of back cover
    c.setFillColor(fg)
    c.setFont(font, 10)
    c.drawCentredString(back_cx, safe_bottom + 0.5 * inch, "Created with Polly Connect")
    c.setFont(font.replace("Bold", "Roman").replace("Courier-Roman", "Courier") if font.replace("Bold", "Roman") in FONT_CHOICES.values() else font, 8)
    c.drawCentredString(back_cx, safe_bottom + 0.2 * inch, "polly-connect.com")

    # ── Trim marks (light gray guidelines) ──
    c.setStrokeColor(Color(0.8, 0.8, 0.8))
    c.setLineWidth(0.25)
    # Vertical trim lines
    for x in [back_left, back_right, spine_right, front_right]:
        c.line(x, 0, x, total_h)
    # Horizontal trim lines
    for y_val in [bottom_trim, top_trim]:
        c.line(0, y_val, total_w, y_val)

    c.save()
    return buf.getvalue()


def _draw_centered_text(c, text, cx, y, font_name, font_size, color, max_width):
    """Draw centered text, shrinking font if needed to fit max_width."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    c.setFillColor(color)
    size = font_size
    while size > 12:
        w = stringWidth(text, font_name, size)
        if w <= max_width:
            break
        size -= 1
    c.setFont(font_name, size)
    c.drawCentredString(cx, y, text)


def _wrap_text(text, font_name, font_size, max_width):
    """Simple word-wrap into lines that fit max_width."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        test = f"{current_line} {word}".strip()
        if stringWidth(test, font_name, font_size) <= max_width:
            current_line = test
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return lines


def generate_blurb_from_chapters(db, tenant_id: int, speaker_name: str = "") -> str:
    """Use GPT to generate a back cover blurb from chapter summaries."""
    # Gather chapter summaries first
    drafts = db.get_chapter_drafts(tenant_id=tenant_id)
    summaries = []
    for d in drafts:
        if d.get("summary"):
            summaries.append(f"Chapter {d['chapter_number']} ({d.get('title', '')}): {d['summary']}")
        elif d.get("content"):
            # Use first 200 chars of content as fallback
            summaries.append(f"Chapter {d['chapter_number']} ({d.get('title', '')}): {d['content'][:200]}...")

    if not summaries:
        return ""

    prompt = f"""Write a compelling back cover blurb (3-4 sentences, ~80 words) for a legacy book.
The book captures the life stories of {speaker_name or 'the author'}, told in their own voice.

Chapter summaries:
{chr(10).join(summaries[:12])}

Write in third person. Make it warm, inviting, and emotional. Do NOT include the book title.
Do NOT use phrases like "this book" — just describe the journey. End with something that makes
the reader want to open the book."""

    try:
        import openai
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.8,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Blurb generation failed: {e}")
        return ""
