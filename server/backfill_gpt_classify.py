"""
One-shot: re-classify every existing memory through GPT.

Pulls each memory's transcript (from the linked story) and asks
gpt-4o-mini for the proper bucket / life_phase / estimated_year /
people / locations / emotions / summary, then updates the row.

Run from /opt/polly-connect/server with:
    sudo OPENAI_API_KEY=$(sudo grep -E "^OPENAI_API_KEY=" /opt/polly-connect/.env | cut -d= -f2-) python3 backfill_gpt_classify.py

Or, if your service env already provides OPENAI_API_KEY in /etc/environment
or systemd's EnvironmentFile, just:
    sudo -E python3 backfill_gpt_classify.py
"""
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Reuse the helper that the live service uses, so the prompt and parsing
# stay in lockstep with the runtime behavior.
from api.web import _gpt_classify_story, _apply_gpt_classification
from core.database import PollyDB


def main():
    db_path = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "polly.db"))
    print(f"DB: {db_path}")

    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY env var not set.")
        sys.exit(1)

    db = PollyDB(db_path=db_path)

    raw = sqlite3.connect(db_path)
    raw.row_factory = sqlite3.Row
    rows = raw.execute("""
        SELECT m.id, m.story_id, m.tenant_id, m.bucket, m.life_phase, m.speaker,
               s.transcript, s.corrected_transcript,
               u.birth_year
        FROM memories m
        LEFT JOIN stories s ON s.id = m.story_id
        LEFT JOIN user_profiles u ON u.tenant_id = m.tenant_id
        ORDER BY m.id
    """).fetchall()

    print(f"Found {len(rows)} memories to reclassify.\n")

    updated = 0
    skipped = 0
    errors = 0
    for r in rows:
        text = (r["corrected_transcript"] or r["transcript"] or "").strip()
        if not text or len(text) < 10:
            print(f"  m{r['id']}: skip (no usable text)")
            skipped += 1
            continue

        try:
            parsed = _gpt_classify_story(text, birth_year=r["birth_year"],
                                          include_formatting=False)
            ok = _apply_gpt_classification(
                db, r["story_id"], r["tenant_id"], parsed,
                fallback_text=text, speaker=r["speaker"],
            )
            if ok:
                updated += 1
                old = f"{r['bucket']}/{r['life_phase']}"
                new = f"{parsed.get('bucket')}/{parsed.get('life_phase')}"
                yr = parsed.get("estimated_year") or "—"
                changed = "  CHANGED" if old != new else ""
                print(f"  m{r['id']:4d} {old:38s} -> {new:38s} year={yr}{changed}")
            else:
                errors += 1
        except Exception as e:
            print(f"  m{r['id']}: ERROR {e}")
            errors += 1

        time.sleep(0.2)  # gentle rate limit

    raw.close()
    print(f"\nUpdated {updated}, skipped {skipped}, errors {errors}.")


if __name__ == "__main__":
    main()
