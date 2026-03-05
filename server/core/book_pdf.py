"""
PDF Book Generator for Polly Connect Legacy Books.

Generates a print-ready 6x9 inch PDF suitable for KDP, Lulu, IngramSpark.
Uses ReportLab for layout and qrcode for audio companion QR codes.

Trim: 6" x 9" (432 x 648 points)
Margins: gutter 0.85", outside 0.65", top 0.75", bottom 0.75"
Works for both softcover and hardcover binding.
"""

import io
import logging
import os
import textwrap
from typing import Dict, List, Optional

from reportlab.lib.pagesizes import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY, TA_RIGHT
from reportlab.lib.colors import HexColor
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image,
    Table, TableStyle, NextPageTemplate, PageTemplate, Frame,
    BaseDocTemplate,
)
from reportlab.lib.units import inch as INCH
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)

# ── Page dimensions (6x9 trim) ──

PAGE_WIDTH = 6 * INCH
PAGE_HEIGHT = 9 * INCH

# Margins (in inches) — KDP-safe for up to 300 pages
GUTTER = 0.85 * INCH       # inside margin (binding side)
OUTSIDE = 0.65 * INCH      # outside margin
TOP = 0.75 * INCH
BOTTOM = 0.75 * INCH

# Text area
TEXT_WIDTH = PAGE_WIDTH - GUTTER - OUTSIDE
TEXT_HEIGHT = PAGE_HEIGHT - TOP - BOTTOM

# QR code config
QR_SIZE = 0.8 * INCH
AUDIO_BASE_URL = "https://polly-connect.com/static/recordings"

BUCKET_LABELS = {
    "ordinary_world": "Everyday Life",
    "call_to_adventure": "Turning Points",
    "crossing_threshold": "Big Decisions",
    "trials_allies_enemies": "Challenges & Helpers",
    "transformation": "How You Changed",
    "return_with_knowledge": "Wisdom & Lessons",
}

PHASE_LABELS = {
    "childhood": "Childhood",
    "adolescence": "Adolescence",
    "young_adult": "Young Adult",
    "adult": "Adult",
    "midlife": "Midlife",
    "elder": "Elder",
    "reflection": "Reflection",
}


def _build_styles():
    """Build custom paragraph styles for the book."""
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name='BookTitle',
        fontName='Times-Bold',
        fontSize=28,
        leading=34,
        alignment=TA_CENTER,
        spaceAfter=12,
        textColor=HexColor('#1a1a1a'),
    ))

    styles.add(ParagraphStyle(
        name='BookSubtitle',
        fontName='Times-Italic',
        fontSize=16,
        leading=20,
        alignment=TA_CENTER,
        spaceAfter=6,
        textColor=HexColor('#555555'),
    ))

    styles.add(ParagraphStyle(
        name='BookAuthor',
        fontName='Times-Roman',
        fontSize=14,
        leading=18,
        alignment=TA_CENTER,
        spaceBefore=24,
        spaceAfter=6,
        textColor=HexColor('#333333'),
    ))

    styles.add(ParagraphStyle(
        name='ChapterTitle',
        fontName='Times-Bold',
        fontSize=22,
        leading=28,
        alignment=TA_LEFT,
        spaceBefore=72,
        spaceAfter=24,
        textColor=HexColor('#1a1a1a'),
    ))

    styles.add(ParagraphStyle(
        name='ChapterSubhead',
        fontName='Times-Italic',
        fontSize=11,
        leading=14,
        alignment=TA_LEFT,
        spaceAfter=18,
        textColor=HexColor('#777777'),
    ))

    # Override the default BodyText style
    styles['BodyText'].fontName = 'Times-Roman'
    styles['BodyText'].fontSize = 11
    styles['BodyText'].leading = 15
    styles['BodyText'].alignment = TA_JUSTIFY
    styles['BodyText'].spaceBefore = 0
    styles['BodyText'].spaceAfter = 8
    styles['BodyText'].firstLineIndent = 18
    styles['BodyText'].textColor = HexColor('#1a1a1a')

    styles.add(ParagraphStyle(
        name='BodyFirst',
        fontName='Times-Roman',
        fontSize=11,
        leading=15,
        alignment=TA_JUSTIFY,
        spaceBefore=0,
        spaceAfter=8,
        firstLineIndent=0,  # first paragraph after heading: no indent
        textColor=HexColor('#1a1a1a'),
    ))

    styles.add(ParagraphStyle(
        name='QRCaption',
        fontName='Times-Italic',
        fontSize=8,
        leading=10,
        alignment=TA_CENTER,
        textColor=HexColor('#888888'),
    ))

    styles.add(ParagraphStyle(
        name='Dedication',
        fontName='Times-Italic',
        fontSize=13,
        leading=18,
        alignment=TA_CENTER,
        spaceBefore=120,
        textColor=HexColor('#333333'),
    ))

    styles.add(ParagraphStyle(
        name='TOCEntry',
        fontName='Times-Roman',
        fontSize=12,
        leading=20,
        alignment=TA_LEFT,
        textColor=HexColor('#1a1a1a'),
    ))

    styles.add(ParagraphStyle(
        name='TOCTitle',
        fontName='Times-Bold',
        fontSize=18,
        leading=24,
        alignment=TA_CENTER,
        spaceBefore=48,
        spaceAfter=24,
        textColor=HexColor('#1a1a1a'),
    ))

    styles.add(ParagraphStyle(
        name='Footer',
        fontName='Times-Roman',
        fontSize=9,
        leading=12,
        alignment=TA_CENTER,
        textColor=HexColor('#999999'),
    ))

    return styles


def _generate_qr_image(url: str, size_px: int = 120) -> Optional[io.BytesIO]:
    """Generate a QR code as an in-memory PNG image."""
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=4,
            border=1,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return buf
    except Exception as e:
        logger.warning(f"QR generation failed: {e}")
        return None


class LegacyBookPDF:
    """Generates a print-ready 6x9 PDF for a family legacy book."""

    def __init__(self, db, book_builder, tenant_id: int = None):
        self.db = db
        self.book_builder = book_builder
        self.tenant_id = tenant_id
        self.styles = _build_styles()
        self._page_count = 0

    def generate(self, speaker_name: str = None,
                 book_title: str = None,
                 subtitle: str = None,
                 dedication: str = None,
                 include_qr_codes: bool = True) -> bytes:
        """
        Generate the full book PDF.

        Returns PDF bytes ready for download/print.
        """
        buf = io.BytesIO()

        # Get chapters and drafts
        chapters = self.book_builder.generate_chapter_outline(speaker=speaker_name)
        drafts = {d["chapter_number"]: d for d in self.db.get_chapter_drafts(tenant_id=self.tenant_id)}

        # Filter to chapters that have drafts or enough content
        printable = []
        for ch in chapters:
            if ch["chapter_number"] in drafts:
                ch["draft"] = drafts[ch["chapter_number"]]
                printable.append(ch)
            elif ch["status"] == "ready":
                # No AI draft — use raw memory text
                ch["draft"] = None
                printable.append(ch)

        if not printable:
            # Generate a placeholder book
            printable = []

        # Determine title
        if not book_title:
            if speaker_name:
                book_title = f"The Story of {speaker_name}"
            else:
                book_title = "A Family Legacy"

        if not subtitle:
            subtitle = "Stories, Memories, and Wisdom"

        # Build document
        doc = SimpleDocTemplate(
            buf,
            pagesize=(PAGE_WIDTH, PAGE_HEIGHT),
            topMargin=TOP,
            bottomMargin=BOTTOM,
            leftMargin=GUTTER,
            rightMargin=OUTSIDE,
        )

        story = []

        # ── Title Page ──
        story.append(Spacer(1, 120))
        story.append(Paragraph(book_title, self.styles['BookTitle']))
        story.append(Spacer(1, 12))
        story.append(Paragraph(subtitle, self.styles['BookSubtitle']))
        if speaker_name:
            story.append(Paragraph(f"As told by {speaker_name}", self.styles['BookAuthor']))
        story.append(Spacer(1, 48))
        story.append(Paragraph(
            "Captured and preserved by Polly Connect",
            self.styles['BookSubtitle'],
        ))
        story.append(PageBreak())

        # ── Copyright / blank page ──
        story.append(Spacer(1, 300))
        story.append(Paragraph(
            f"Copyright &copy; 2026. All rights reserved.",
            ParagraphStyle(
                name='Copyright',
                fontName='Times-Roman',
                fontSize=9,
                leading=12,
                alignment=TA_CENTER,
                textColor=HexColor('#999999'),
            ),
        ))
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "This book was created using Polly Connect, a voice-powered<br/>"
            "family legacy preservation system. The stories within were<br/>"
            "spoken aloud and captured in the storyteller's own words.",
            ParagraphStyle(
                name='CopyrightBody',
                fontName='Times-Italic',
                fontSize=8,
                leading=11,
                alignment=TA_CENTER,
                textColor=HexColor('#aaaaaa'),
            ),
        ))
        story.append(PageBreak())

        # ── Dedication (optional) ──
        if dedication:
            story.append(Paragraph(dedication, self.styles['Dedication']))
            story.append(PageBreak())

        # ── Table of Contents ──
        story.append(Paragraph("Contents", self.styles['TOCTitle']))
        for ch in printable:
            entry = f"Chapter {ch['chapter_number']}:&nbsp;&nbsp;&nbsp;{ch['title']}"
            story.append(Paragraph(entry, self.styles['TOCEntry']))
        story.append(PageBreak())

        # ── Chapters ──
        for ch in printable:
            # Chapter heading
            story.append(Paragraph(
                f"Chapter {ch['chapter_number']}",
                ParagraphStyle(
                    name='ChapterNum',
                    fontName='Times-Roman',
                    fontSize=12,
                    leading=16,
                    alignment=TA_LEFT,
                    spaceBefore=72,
                    spaceAfter=4,
                    textColor=HexColor('#999999'),
                ),
            ))
            story.append(Paragraph(ch['title'], self.styles['ChapterTitle']))

            # Bucket / phase subtitle
            bucket_label = BUCKET_LABELS.get(ch.get('bucket', ''), '')
            phase_label = PHASE_LABELS.get(ch.get('life_phase', ''), '')
            if bucket_label or phase_label:
                subhead = " — ".join(filter(None, [bucket_label, phase_label]))
                story.append(Paragraph(subhead, self.styles['ChapterSubhead']))

            # Chapter body
            draft = ch.get("draft")
            if draft and draft.get("content"):
                # AI-generated chapter draft
                paragraphs = draft["content"].split("\n\n")
                for i, para in enumerate(paragraphs):
                    para = para.strip()
                    if not para:
                        continue
                    # Escape HTML entities
                    para = para.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    style = self.styles['BodyFirst'] if i == 0 else self.styles['BodyText']
                    story.append(Paragraph(para, style))
            else:
                # No draft — use raw memory texts
                memories = []
                for mid in ch.get("memory_ids", []):
                    mem = self.db.get_memory_by_id(mid)
                    if mem:
                        memories.append(mem)

                if memories:
                    for i, mem in enumerate(memories):
                        text = mem.get("text", mem.get("text_summary", ""))
                        if not text:
                            continue
                        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                        speaker = mem.get("speaker", "")
                        if speaker:
                            text = f"<i>{speaker}:</i> {text}"
                        style = self.styles['BodyFirst'] if i == 0 else self.styles['BodyText']
                        story.append(Paragraph(text, style))
                        story.append(Spacer(1, 4))
                else:
                    story.append(Paragraph(
                        "<i>This chapter is still being written...</i>",
                        self.styles['BodyFirst'],
                    ))

            # QR code for audio companion
            if include_qr_codes:
                audio_keys = self._get_chapter_audio_keys(ch)
                if audio_keys:
                    story.append(Spacer(1, 18))
                    # Use first audio recording for the QR
                    audio_url = f"{AUDIO_BASE_URL}/{audio_keys[0]}"
                    qr_buf = _generate_qr_image(audio_url)
                    if qr_buf:
                        story.append(Spacer(1, 6))
                        img = Image(qr_buf, width=QR_SIZE, height=QR_SIZE)
                        story.append(img)
                        story.append(Paragraph(
                            "Scan to hear the original voice recording",
                            self.styles['QRCaption'],
                        ))

            story.append(PageBreak())

        # ── Back matter ──
        story.append(Spacer(1, 120))
        story.append(Paragraph(
            "This book was created with love by Polly Connect.",
            self.styles['Dedication'],
        ))
        story.append(Spacer(1, 24))
        story.append(Paragraph(
            "Every story matters. Every voice deserves to be heard.",
            ParagraphStyle(
                name='BackMatter',
                fontName='Times-Italic',
                fontSize=11,
                leading=15,
                alignment=TA_CENTER,
                textColor=HexColor('#777777'),
            ),
        ))

        # Build PDF
        try:
            doc.build(story, onFirstPage=self._page_header_footer,
                      onLaterPages=self._page_header_footer)
        except Exception as e:
            logger.error(f"PDF generation failed: {e}")
            # Try without the import that might fail
            try:
                doc.build(story)
            except Exception as e2:
                logger.error(f"PDF generation failed completely: {e2}")
                raise

        return buf.getvalue()

    def _page_header_footer(self, canvas, doc):
        """Add page numbers to each page."""
        self._page_count += 1
        page_num = self._page_count

        # Skip page number on title page and copyright
        if page_num <= 2:
            return

        canvas.saveState()
        canvas.setFont('Times-Roman', 9)
        canvas.setFillColor(HexColor('#999999'))

        # Page number centered at bottom
        canvas.drawCentredString(
            PAGE_WIDTH / 2,
            BOTTOM - 20,
            str(page_num),
        )
        canvas.restoreState()

    def _get_chapter_audio_keys(self, chapter: dict) -> List[str]:
        """Get audio file keys for memories in a chapter."""
        keys = []
        for mid in chapter.get("memory_ids", []):
            mem = self.db.get_memory_by_id(mid)
            if mem and mem.get("story_id"):
                story = self.db.get_story_by_id(mem["story_id"])
                if story and story.get("audio_s3_key"):
                    keys.append(story["audio_s3_key"])
        return keys
