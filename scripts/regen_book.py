"""
Regenerate Glen Rogers Legacy Book PDF from production database.
Uses the updated inline photo placement + date-aware pipeline.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from server.core.database import PollyDB
from server.core.book_builder import BookBuilder
from server.core.book_pdf import LegacyBookPDF
from server.core.followup_generator import FollowupGenerator

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "polly_server.db")
OUTPUT_PATH = os.path.expanduser("~/Desktop/Glen_Rogers_book.pdf")
TENANT_ID = 1
OWNER_BIRTH_YEAR = 1978


async def main():
    db = PollyDB(DB_PATH)
    fg = FollowupGenerator()
    bb = BookBuilder(db, followup_generator=fg)

    if not fg.available:
        print("ERROR: OpenAI not available — set OPENAI_API_KEY in .env")
        return

    conn = db._get_connection()

    # ── Fix Ali's new photos: set estimated_year from content ──
    print("=== Fixing undated memories ===")
    undated = conn.execute(
        "SELECT id, story_id, text_summary, text FROM memories WHERE tenant_id = ? AND estimated_year IS NULL",
        (TENANT_ID,)
    ).fetchall()

    for mid, story_id, summary, text in undated:
        content = (text or summary or "").lower()
        est_year = None
        bucket = "ordinary_world"
        life_phase = "childhood"
        speaker = None

        # Get story info
        story = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()

        # Check for year clues in text
        if story:
            photo_id = story[19] if len(story) > 19 else None  # photo_id column
            if photo_id:
                photo = conn.execute("SELECT caption, date_taken FROM photos WHERE id = ?", (photo_id,)).fetchone()
                if photo and photo[1]:
                    yr_match = re.search(r'(19\d{2}|20\d{2})', str(photo[1]))
                    if yr_match:
                        est_year = int(yr_match.group(1))

        # Fallback: parse from text
        if not est_year:
            yr_match = re.search(r'(19\d{2}|20\d{2})', content)
            if yr_match:
                est_year = int(yr_match.group(1))

        # Content-based guesses
        if not est_year:
            if "wedding" in content or "wedding day" in content:
                est_year = 2014  # Glen & Ali wedding
            elif "birth of brooklyn" in content or "baby brooklyn" in content:
                est_year = 2019  # Brooklyn born Feb 2019
            elif "newborn" in content:
                est_year = 2019

        if est_year:
            # Assign bucket/phase based on year
            age = est_year - OWNER_BIRTH_YEAR
            if age <= 12:
                bucket, life_phase = "ordinary_world", "childhood"
            elif age <= 18:
                bucket, life_phase = "call_to_adventure", "adolescence"
            elif age <= 30:
                bucket, life_phase = "crossing_threshold", "young_adult"
            elif age <= 50:
                bucket, life_phase = "trials_allies_enemies", "adult"
            else:
                bucket, life_phase = "return_with_knowledge", "reflection"

            owner_age = age
            conn.execute("""
                UPDATE memories SET estimated_year = ?, owner_age = ?, bucket = ?, life_phase = ?
                WHERE id = ?
            """, (est_year, owner_age, bucket, life_phase, mid))
            print(f"  Fixed mid={mid}: ~{est_year} (age {owner_age}) -> {bucket}/{life_phase}")
        else:
            print(f"  SKIP mid={mid}: no year clue in '{(summary or '')[:50]}'")

    conn.commit()

    # ── Clear old drafts and regenerate ──
    conn.execute("DELETE FROM chapter_drafts WHERE tenant_id = ?", (TENANT_ID,))
    conn.commit()
    print("\nCleared old chapter drafts")

    chapters = bb.generate_chapter_outline(tenant_id=TENANT_ID)
    print(f"Found {len(chapters)} chapters in outline\n")

    for ch in chapters:
        yr = ch.get("year_range")
        yr_str = f", ~{yr[0]}-{yr[1]}" if yr else ""
        print(f"  Ch {ch['chapter_number']}: {ch['title']} ({ch['memory_count']} memories{yr_str}) [{ch['status']}]")

    previous_summaries = []
    for ch in chapters:
        print(f"\nGenerating Ch {ch['chapter_number']}: \"{ch['title']}\" ...")

        content = await bb.generate_chapter_draft(
            ch, speaker="Glen Rogers", tenant_id=TENANT_ID,
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

            # Check for photo markers
            markers = re.findall(r'\[PHOTO:\d+\]', content)
            if markers:
                print(f"  Photos placed inline: {markers}")

            summary = await bb.generate_chapter_summary(content)
            if summary:
                db.update_chapter_summary(draft_id, summary)
                previous_summaries.append(summary)
                print(f"  Summary: {summary[:80]}...")
        else:
            print(f"  FAILED — no content returned")

    # ── Generate PDF ──
    print(f"\n=== Generating PDF ===")
    pdf_gen = LegacyBookPDF(db, bb, tenant_id=TENANT_ID)
    pdf_bytes = pdf_gen.generate(
        speaker_name=None,
        book_title="The Story of Glen Rogers",
        dedication="For Brooklyn, Liam, and Mia -- so you know where you came from.",
        include_qr_codes=True,
    )

    with open(OUTPUT_PATH, "wb") as f:
        f.write(pdf_bytes)
    print(f"\nPDF saved to {OUTPUT_PATH} ({len(pdf_bytes):,} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
