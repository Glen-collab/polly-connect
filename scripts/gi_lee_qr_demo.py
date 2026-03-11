#!/usr/bin/env python3
"""Set up demo audio files for Gi Lee's stories so QR codes appear in the PDF export.

Creates short placeholder WAV files and links them to stories/memories.
Run on the EC2 server: python3.11 scripts/gi_lee_qr_demo.py
"""
import sqlite3
import struct
import os

DB_PATH = "polly.db"
TENANT_ID = 2
RECORDINGS_DIR = "server/static/recordings"

# We'll pick ~10 stories spread across chapters to get QR codes in most chapters
# These are the story IDs we want to add audio to (one per speaker for variety)
# We'll query and pick them dynamically based on what exists


def make_silent_wav(filename, duration_seconds=2, sample_rate=16000):
    """Create a short silent WAV file for demo purposes."""
    num_samples = int(sample_rate * duration_seconds)
    # PCM 16-bit mono
    data_size = num_samples * 2
    filepath = os.path.join(RECORDINGS_DIR, filename)

    with open(filepath, "wb") as f:
        # RIFF header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        # fmt chunk
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))       # chunk size
        f.write(struct.pack("<H", 1))        # PCM
        f.write(struct.pack("<H", 1))        # mono
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", sample_rate * 2))  # byte rate
        f.write(struct.pack("<H", 2))        # block align
        f.write(struct.pack("<H", 16))       # bits per sample
        # data chunk
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(b"\x00" * data_size)         # silence

    return filepath


def main():
    os.makedirs(RECORDINGS_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Get all Gi Lee stories
    cur.execute("""
        SELECT id, speaker_name, transcript, source
        FROM stories WHERE tenant_id = ?
        ORDER BY id
    """, (TENANT_ID,))
    stories = [dict(r) for r in cur.fetchall()]
    print(f"Found {len(stories)} stories for tenant {TENANT_ID}")

    # Get all memories with story_id links
    cur.execute("""
        SELECT id, story_id, speaker, bucket, life_phase
        FROM memories WHERE tenant_id = ?
        ORDER BY id
    """, (TENANT_ID,))
    memories = [dict(r) for r in cur.fetchall()]
    print(f"Found {len(memories)} memories for tenant {TENANT_ID}")

    # Pick stories to add audio to — spread across different speakers and buckets
    # Get unique speakers
    speakers_seen = set()
    selected_stories = []
    for s in stories:
        speaker = s["speaker_name"]
        if speaker not in speakers_seen and len(selected_stories) < 12:
            speakers_seen.add(speaker)
            selected_stories.append(s)

    # If we have fewer than 10, add more from different stories
    if len(selected_stories) < 10:
        for s in stories:
            if s["id"] not in [ss["id"] for ss in selected_stories]:
                selected_stories.append(s)
                if len(selected_stories) >= 12:
                    break

    print(f"\nSelected {len(selected_stories)} stories for QR code demo:")
    for s in selected_stories:
        print(f"  Story {s['id']}: {s['speaker_name']} — {s['transcript'][:60]}...")

    # Create WAV files and update stories
    updated = 0
    for s in selected_stories:
        wav_name = f"demo_gi_lee_{s['id']}.wav"
        filepath = make_silent_wav(wav_name, duration_seconds=3)
        print(f"  Created: {filepath}")

        # Update story with audio_s3_key and qr_in_book=1
        cur.execute("""
            UPDATE stories
            SET audio_s3_key = ?, qr_in_book = 1, duration_seconds = 3.0
            WHERE id = ? AND tenant_id = ?
        """, (wav_name, s["id"], TENANT_ID))
        updated += 1

    conn.commit()
    print(f"\nUpdated {updated} stories with audio_s3_key")

    # Verify memories link to stories
    cur.execute("""
        SELECT m.id as mem_id, m.story_id, m.bucket, m.life_phase,
               s.audio_s3_key, s.qr_in_book
        FROM memories m
        JOIN stories s ON m.story_id = s.id
        WHERE m.tenant_id = ? AND s.audio_s3_key IS NOT NULL
    """, (TENANT_ID,))
    linked = cur.fetchall()
    print(f"\nMemories linked to stories with audio: {len(linked)}")
    for r in linked:
        print(f"  Memory {r[0]} → Story {r[1]} ({r[2]}/{r[3]}) → {r[4]}")

    # Check chapter_drafts have memory_ids that reference these memories
    cur.execute("""
        SELECT chapter_number, title, memory_ids
        FROM chapter_drafts WHERE tenant_id = ?
        ORDER BY chapter_number
    """, (TENANT_ID,))
    drafts = cur.fetchall()

    import json
    print(f"\nChapter drafts with QR-linked memories:")
    for d in drafts:
        ch_num, title, mem_ids_json = d
        try:
            mem_ids = json.loads(mem_ids_json)
        except:
            mem_ids = []
        # Check how many of these memory IDs have audio-linked stories
        audio_count = 0
        for mid in mem_ids:
            cur.execute("""
                SELECT s.audio_s3_key FROM memories m
                JOIN stories s ON m.story_id = s.id
                WHERE m.id = ? AND s.audio_s3_key IS NOT NULL
            """, (mid,))
            if cur.fetchone():
                audio_count += 1
        print(f"  Ch {ch_num}: {title} — {audio_count}/{len(mem_ids)} memories have audio")

    conn.close()
    print("\nDone! QR codes should now appear in the PDF export.")


if __name__ == "__main__":
    main()
