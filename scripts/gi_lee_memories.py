#!/usr/bin/env python3
"""Extract memories from Gi Lee stories for book builder."""
import sqlite3
import json
import hashlib

DB_PATH = "polly.db"

# Map chapter/theme to Jungian bucket and life phase
THEME_MAP = {
    "family_kitchen": ("ordinary_world", "childhood"),
    "family_characters": ("ordinary_world", "childhood"),
    "holidays": ("ordinary_world", "childhood"),
    "growing_up_work": ("call_to_adventure", "adolescence"),
    "courtship": ("crossing_threshold", "young_adult"),
    "raising_kids": ("trials_allies_enemies", "adult"),
    "neighborhood": ("ordinary_world", "childhood"),
    "faith_and_church": ("transformation", "midlife"),
    "music_and_fun": ("ordinary_world", "childhood"),
    "lessons_and_wisdom": ("return_with_knowledge", "reflection"),
}


def extract_people(tags):
    return [t[1] for t in tags if t[0] == "person"]


def extract_locations(tags):
    return [t[1] for t in tags if t[0] == "place"]


def make_summary(text, max_len=120):
    words = text.split()
    if len(words) <= 20:
        return text
    return " ".join(words[:20]) + "..."


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT id FROM tenants WHERE name='The Lee Family'")
    tenant_id = cur.fetchone()[0]

    # Get all stories for this tenant
    cur.execute("SELECT id, speaker_name, chapter, transcript FROM stories WHERE tenant_id=?",
                (tenant_id,))
    stories = cur.fetchall()

    count = 0
    for story_id, speaker, chapter, transcript in stories:
        bucket, life_phase = THEME_MAP.get(chapter, ("ordinary_world", "unknown"))

        # Get tags for this story
        cur.execute("SELECT tag_type, tag_value FROM story_tags WHERE story_id=?", (story_id,))
        tags = cur.fetchall()

        people = json.dumps(extract_people(tags))
        locations = json.dumps(extract_locations(tags))
        summary = make_summary(transcript)

        # Create fingerprint for dedup
        fp_parts = [bucket, speaker or "", ",".join(sorted(extract_people(tags))),
                     ",".join(sorted(extract_locations(tags))), life_phase]
        fingerprint = "::".join(fp_parts)

        cur.execute("""INSERT INTO memories
            (story_id, speaker, bucket, life_phase, text_summary, text, people, locations,
             emotions, fingerprint, verification_status, tenant_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (story_id, speaker, bucket, life_phase, summary, transcript,
             people, locations, "[]", fingerprint, "verified", tenant_id))
        count += 1

    conn.commit()
    conn.close()
    print(f"Created {count} memories for tenant {tenant_id}")

    # Verify coverage
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT bucket, life_phase, COUNT(*) FROM memories WHERE tenant_id=? GROUP BY bucket, life_phase ORDER BY bucket",
                (tenant_id,))
    print("\nMemory coverage:")
    for row in cur.fetchall():
        print(f"  {row[0]} / {row[1]}: {row[2]}")
    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
