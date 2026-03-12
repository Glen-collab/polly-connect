"""
Fill timeline data for Glen Rogers (tenant_id=1), retag stories, generate book PDF.
"""
import sys, os
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

TENANT_ID = 1
OUTPUT_PATH = "/tmp/Glen_Rogers_book.pdf"

# ── Family birth years ──
FAMILY_DATA = {
    "Evelyn Wikman": {"birth_year": 1930},
    "Glen Wikman": {"birth_year": 1928, "deceased_year": 2020},
    "Cindy Vinopal": {"birth_year": 1955},
    "Don Rogers": {"birth_year": 1975},
    "Mickin Rogers": {"birth_year": 1976},
    "Traci Vinopal": {"birth_year": 1973},
    "Ali Rogers": {"birth_year": 1980},
    "Brooklyn": {"birth_year": 2018},
    "Liam": {"birth_year": 2020},
    "Mia": {"birth_year": 2022},
    "Johnnie": {"birth_year": 1967},
    "Sandy": {"birth_year": 1953},
    "Evey": {"birth_year": 1955},
    "Sue": {"birth_year": 1957},
    "Linda": {"birth_year": 1959},
    "Sherry": {"birth_year": 1961},
    "Sally": {"birth_year": 1963},
    "Matt Lubinski": {"birth_year": 1978},
    "Erik Meyer": {"birth_year": 1978},
}

# ── Manual estimated years for stories (from transcript clues) ──
# Glen born 1978
STORY_OVERRIDES = {
    4:  {"estimated_year": 1986, "speaker": "Glen", "bucket": "ordinary_world", "life_phase": "childhood"},
    5:  {"estimated_year": 1984, "speaker": "Glen", "bucket": "ordinary_world", "life_phase": "childhood"},
    6:  {"estimated_year": 1987, "speaker": "Glen", "bucket": "ordinary_world", "life_phase": "childhood"},
    7:  {"estimated_year": 1994, "speaker": "Glen", "bucket": "call_to_adventure", "life_phase": "adolescence"},
    8:  {"estimated_year": 2026, "speaker": "Glen", "bucket": "return_with_knowledge", "life_phase": "reflection"},
    9:  {"estimated_year": 1989, "speaker": "Glen", "bucket": "ordinary_world", "life_phase": "childhood"},
    10: {"estimated_year": 1988, "speaker": "Glen", "bucket": "ordinary_world", "life_phase": "childhood"},
    11: {"estimated_year": 1993, "speaker": "Glen", "bucket": "call_to_adventure", "life_phase": "adolescence"},
    12: {"estimated_year": 2022, "speaker": "Glen", "bucket": "return_with_knowledge", "life_phase": "reflection"},
    13: {"estimated_year": 1990, "speaker": "Glen", "bucket": "ordinary_world", "life_phase": "childhood"},
    14: {"estimated_year": 1997, "speaker": "Glen", "bucket": "crossing_threshold", "life_phase": "young_adult"},
    16: {"estimated_year": 2025, "speaker": "Ali and Brooklyn, Mia and Liam", "bucket": "return_with_knowledge", "life_phase": "reflection"},
    17: {"estimated_year": 2025, "speaker": "Glen", "bucket": "return_with_knowledge", "life_phase": "reflection"},
    18: {"estimated_year": 1986, "speaker": "Glen", "bucket": "ordinary_world", "life_phase": "childhood"},
    19: {"estimated_year": 1988, "speaker": "Glen", "bucket": "ordinary_world", "life_phase": "childhood"},
    20: {"estimated_year": 2019, "speaker": "Glen", "bucket": "trials_allies_enemies", "life_phase": "adult"},
    21: {"estimated_year": 2003, "speaker": "Glen", "bucket": "crossing_threshold", "life_phase": "young_adult"},
    22: {"estimated_year": 2005, "speaker": "Glen", "bucket": "crossing_threshold", "life_phase": "young_adult"},
    82: {"estimated_year": 2010, "speaker": "Glen", "bucket": "transformation", "life_phase": "adult"},
    83: {"estimated_year": 2026, "speaker": "Glen", "bucket": "return_with_knowledge", "life_phase": "reflection"},
}

OWNER_BIRTH_YEAR = 1978


async def main():
    db = PollyDB("polly.db")
    fg = FollowupGenerator()
    bb = BookBuilder(db, followup_generator=fg)

    if not fg.available:
        print("ERROR: OpenAI not available")
        return

    conn = db._get_connection()

    # ── 1. Update family birth years / deceased years ──
    print("=== Updating family members ===")
    fam = conn.execute("SELECT id, name FROM family_members WHERE tenant_id = ?", (TENANT_ID,)).fetchall()
    for fid, fname in fam:
        data = FAMILY_DATA.get(fname)
        if data:
            by = data.get("birth_year")
            dy = data.get("deceased_year")
            if by:
                conn.execute("UPDATE family_members SET birth_year = ? WHERE id = ?", (by, fid))
            if dy:
                conn.execute("UPDATE family_members SET deceased_year = ?, deceased = 1 WHERE id = ?", (dy, fid))
            print(f"  {fname}: born={by} died={dy}")
    conn.commit()

    # ── 2. Apply story overrides (speaker, estimated_year, bucket, life_phase) ──
    print("\n=== Applying story overrides ===")
    for story_id, overrides in STORY_OVERRIDES.items():
        est_year = overrides["estimated_year"]
        speaker = overrides["speaker"]
        bucket = overrides["bucket"]
        life_phase = overrides["life_phase"]
        owner_age = est_year - OWNER_BIRTH_YEAR

        # Determine confidence
        transcript = conn.execute("SELECT transcript FROM stories WHERE id = ?", (story_id,)).fetchone()
        txt = (transcript[0] or "").lower() if transcript else ""
        # Check for explicit year mentions
        import re
        explicit = re.search(r'\b(19\d{2}|20[012]\d)\b', txt)
        if explicit:
            confidence = "high"
        elif any(p in txt for p in ["when i was", "growing up", "as a kid", "high school", "grade school", "freshman"]):
            confidence = "medium"
        else:
            confidence = "low"

        # Update story speaker
        conn.execute("UPDATE stories SET speaker_name = ? WHERE id = ? AND (speaker_name IS NULL OR speaker_name = '')",
                      (speaker, story_id))

        # Update memory
        conn.execute("""
            UPDATE memories SET estimated_year = ?, owner_age = ?, year_confidence = ?,
                   speaker = ?, bucket = ?, life_phase = ?
            WHERE story_id = ? AND tenant_id = ?
        """, (est_year, owner_age, confidence, speaker, bucket, life_phase, story_id, TENANT_ID))

        print(f"  Story {story_id}: ~{est_year} (age {owner_age}), {bucket}/{life_phase}, conf={confidence}")

    conn.commit()

    # ── 3. Ensure all photos have photo_in_book = 1 ──
    print("\n=== Setting all photos to photo_in_book=1 ===")
    conn.execute("UPDATE stories SET photo_in_book = 1 WHERE tenant_id = ? AND photo_id IS NOT NULL", (TENANT_ID,))
    conn.execute("UPDATE stories SET qr_in_book = 1 WHERE tenant_id = ? AND audio_s3_key IS NOT NULL", (TENANT_ID,))
    conn.commit()
    print("  Done — all photos and QR codes enabled for book")

    # ── 4. Re-tag all stories to pick up year tags ──
    print("\n=== Re-tagging stories ===")
    stories = conn.execute("SELECT id, COALESCE(corrected_transcript, transcript) FROM stories WHERE tenant_id = ?", (TENANT_ID,)).fetchall()
    for sid, transcript in stories:
        if transcript:
            db.auto_tag_story(sid, transcript, tenant_id=TENANT_ID)
    print(f"  Re-tagged {len(stories)} stories")

    # ── 5. Clear existing drafts and generate chapters ──
    conn.execute("DELETE FROM chapter_drafts WHERE tenant_id = ?", (TENANT_ID,))
    conn.commit()
    print("\nCleared existing chapter drafts")

    chapters = bb.generate_chapter_outline(tenant_id=TENANT_ID)
    print(f"Found {len(chapters)} chapters in outline")

    previous_summaries = []
    for ch in chapters:
        yr = ch.get("year_range")
        yr_str = f", ~{yr[0]}-{yr[1]}" if yr else ""
        print(f"\nGenerating Ch {ch['chapter_number']}: {ch['title']} "
              f"({ch['bucket']}/{ch['life_phase']}, {ch['memory_count']} memories{yr_str})...")

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

            summary = await bb.generate_chapter_summary(content)
            if summary:
                db.update_chapter_summary(draft_id, summary)
                previous_summaries.append(summary)
                print(f"  Summary: {summary[:80]}...")
        else:
            print(f"  FAILED — no content returned")

    # ── 6. Generate PDF ──
    print(f"\nGenerating PDF...")
    pdf_gen = LegacyBookPDF(db, bb, tenant_id=TENANT_ID)
    pdf_bytes = pdf_gen.generate(
        speaker_name=None,  # Don't filter by speaker — use tenant_id only
        book_title="The Story of Glen Rogers",
        dedication="For Brooklyn, Liam, and Mia — so you know where you came from.",
    )

    with open(OUTPUT_PATH, "wb") as f:
        f.write(pdf_bytes)
    print(f"PDF saved to {OUTPUT_PATH} ({len(pdf_bytes):,} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
