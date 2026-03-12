"""
Regenerate all chapter drafts for Gi Lee (tenant_id=2) with timeline-enriched GPT prompt,
then export as PDF to ~/Desktop/Gi_lee_book.pdf
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from server.core.database import PollyDB
from server.core.book_builder import BookBuilder
from server.core.book_pdf import LegacyBookPDF
from server.core.followup_generator import FollowupGenerator

TENANT_ID = 2
OUTPUT_PATH = "/tmp/Gi_lee_book.pdf"

async def main():
    db = PollyDB("polly.db")
    fg = FollowupGenerator()
    bb = BookBuilder(db, followup_generator=fg)

    if not fg.available:
        print("ERROR: OpenAI not available — cannot regenerate chapters")
        return

    # Get chapter outline
    chapters = bb.generate_chapter_outline(tenant_id=TENANT_ID)
    print(f"Found {len(chapters)} chapters in outline")

    # Delete existing drafts so we regenerate fresh
    conn = db._get_connection()
    conn.execute("DELETE FROM chapter_drafts WHERE tenant_id = ?", (TENANT_ID,))
    conn.commit()
    print("Cleared existing chapter drafts")

    # Regenerate each chapter with timeline context + continuity
    previous_summaries = []
    for ch in chapters:
        yr = ch.get("year_range")
        yr_str = f", ~{yr[0]}-{yr[1]}" if yr else ""
        print(f"\nGenerating Ch {ch['chapter_number']}: {ch['title']} "
              f"({ch['bucket']}/{ch['life_phase']}, {ch['memory_count']} memories{yr_str})...")

        content = await bb.generate_chapter_draft(
            ch, speaker="Gi Lee", tenant_id=TENANT_ID,
            previous_summaries=previous_summaries if previous_summaries else None,
        )

        if content:
            draft_id = db.save_chapter_draft(
                chapter_number=ch["chapter_number"],
                title=ch["title"],
                bucket=ch["bucket"],
                life_phase=ch["life_phase"],
                memory_ids=json.dumps(ch.get("memory_ids", [])),
                content=content,
                tenant_id=TENANT_ID,
            )
            print(f"  Saved ({len(content)} chars)")

            # Generate summary for continuity chain
            summary = await bb.generate_chapter_summary(content)
            if summary:
                db.update_chapter_summary(draft_id, summary)
                previous_summaries.append(summary)
                print(f"  Summary: {summary[:80]}...")
        else:
            print(f"  FAILED — no content returned")

    # Now generate the PDF
    print(f"\nGenerating PDF...")
    pdf_gen = LegacyBookPDF(db, bb, tenant_id=TENANT_ID)
    pdf_bytes = pdf_gen.generate(
        speaker_name="Gi Lee",
        book_title="The Story of Gi Lee",
        dedication="For the grandkids — so they know where they came from.",
    )

    with open(OUTPUT_PATH, "wb") as f:
        f.write(pdf_bytes)
    print(f"PDF saved to {OUTPUT_PATH} ({len(pdf_bytes):,} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
