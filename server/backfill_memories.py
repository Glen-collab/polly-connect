"""
One-shot backfill: create memory rows for stories that are missing them.

Run from /opt/polly-connect/server with:
    sudo python3 backfill_memories.py
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.database import Database
from core.memory_extractor import MemoryExtractor


def main():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "polly.db")
    db_path = os.path.normpath(db_path)
    print(f"DB: {db_path}")

    db = Database(db_path=db_path)
    extractor = MemoryExtractor()

    raw = sqlite3.connect(db_path)
    raw.row_factory = sqlite3.Row
    rows = raw.execute("""
        SELECT s.id, s.transcript, s.corrected_transcript, s.speaker_name,
               s.tenant_id, s.question_text, s.source
        FROM stories s
        WHERE NOT EXISTS (SELECT 1 FROM memories m WHERE m.story_id = s.id)
        ORDER BY s.id
    """).fetchall()

    print(f"Found {len(rows)} stories without memory rows.\n")

    created = 0
    skipped = 0
    for r in rows:
        text = (r["corrected_transcript"] or r["transcript"] or "").strip()
        if not text or len(text) < 5:
            print(f"  story {r['id']}: skip (no usable text)")
            skipped += 1
            continue

        mem_data = extractor.extract(
            text=text,
            question=r["question_text"],
            speaker=r["speaker_name"],
        )
        memory_id = db.save_memory(
            story_id=r["id"],
            speaker=r["speaker_name"],
            bucket=mem_data["bucket"],
            life_phase=mem_data["life_phase"],
            text_summary=mem_data["text_summary"],
            text=text,
            people=mem_data["people"],
            locations=mem_data["locations"],
            emotions=mem_data["emotions"],
            fingerprint=extractor.compute_fingerprint(mem_data),
            tenant_id=r["tenant_id"],
        )
        created += 1
        preview = (mem_data["text_summary"] or text)[:60]
        print(f"  story {r['id']} -> memory {memory_id} "
              f"[{mem_data['bucket']}/{mem_data['life_phase']}] {preview}")

    raw.close()
    print(f"\nCreated {created} memory row(s), skipped {skipped}.")


if __name__ == "__main__":
    main()
