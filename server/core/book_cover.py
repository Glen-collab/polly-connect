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


# Bundled font families (ReportLab built-ins)
FONT_CHOICES = {
    "Helvetica": "Helvetica",
    "Helvetica-Bold": "Helvetica-Bold",
    "Times-Roman": "Times-Roman",
    "Times-Bold": "Times-Bold",
    "Courier": "Courier",
    "Courier-Bold": "Courier-Bold",
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
) -> bytes:
    """
    Generate a KDP-ready full wrap cover PDF.

    Returns PDF bytes.
    """
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
    front_cx = front_left + (TRIM_W * inch) / 2
    safe_top = top_trim - SAFE_ZONE * inch
    safe_bottom = bottom_trim + SAFE_ZONE * inch

    # Cover photo (if provided)
    if cover_photo_path and os.path.exists(cover_photo_path):
        try:
            img = ImageReader(cover_photo_path)
            iw, ih = img.getSize()
            # Scale to fit within front cover area with some padding
            max_w = (TRIM_W - SAFE_ZONE * 2) * inch
            max_h = 4.0 * inch  # leave room for title above/below
            scale = min(max_w / iw, max_h / ih)
            draw_w = iw * scale
            draw_h = ih * scale
            # Center horizontally, position in middle of cover
            img_x = front_cx - draw_w / 2
            img_y = bottom_trim + (TRIM_H * inch) / 2 - draw_h / 2
            c.drawImage(img, img_x, img_y, draw_w, draw_h, preserveAspectRatio=True)
        except Exception as e:
            logger.warning(f"Cover photo failed: {e}")

    # Title
    c.setFillColor(fg)
    c.setFont(font, 36)
    # Wrap long titles
    title_y = safe_top - 0.5 * inch
    if cover_photo_path and os.path.exists(cover_photo_path):
        title_y = safe_top - 0.4 * inch  # above the photo

    _draw_centered_text(c, title, front_cx, title_y, font, 36, fg,
                        max_width=(TRIM_W - SAFE_ZONE * 2) * inch)

    # Subtitle
    if subtitle:
        c.setFont(font.replace("Bold", "Roman").replace("Courier-Roman", "Courier"), 18)
        sub_font = font.replace("Bold", "Roman").replace("Courier-Roman", "Courier")
        if sub_font not in FONT_CHOICES.values():
            sub_font = font
        _draw_centered_text(c, subtitle, front_cx, title_y - 0.5 * inch,
                            sub_font, 18, fg,
                            max_width=(TRIM_W - SAFE_ZONE * 2) * inch)

    # Author name at bottom
    if author_name:
        c.setFillColor(fg)
        c.setFont(font, 20)
        c.drawCentredString(front_cx, safe_bottom + 0.3 * inch, author_name)

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
        # Draw blurb text with word wrapping
        c.setFillColor(fg)
        blurb_font = font.replace("Bold", "Roman").replace("Courier-Roman", "Courier")
        if blurb_font not in FONT_CHOICES.values():
            blurb_font = font
        blurb_size = 12
        c.setFont(blurb_font, blurb_size)
        lines = _wrap_text(blurb, blurb_font, blurb_size, back_text_width)
        y = safe_top - 1.0 * inch
        line_height = blurb_size * 1.4
        for line in lines:
            if y < safe_bottom + 1.0 * inch:
                break
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
