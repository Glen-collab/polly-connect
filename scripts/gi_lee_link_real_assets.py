#!/usr/bin/env python3
"""Link real photos and audio from tenant 1 (Glen) into Gi Lee's tenant for demo.

Copies photo records (pointing to same files on disk) and updates Gi Lee's stories
with real audio_s3_key values so QR codes play actual voice recordings.

Run on EC2: python3.11 scripts/gi_lee_link_real_assets.py
"""
import sqlite3
import shutil
import os

DB_PATH = "polly.db"
GI_TENANT = 2
GLEN_TENANT = 1
RECORDINGS_DIR = "server/static/recordings"
UPLOADS_DIR = "server/static/uploads"

# Map Glen's photos to Gi Lee stories by theme fit:
#   Photo 2 (Brooklyn at Harley) → family/kids theme → assign to a Lily story
#   Photo 3 (Family cabin gathering) → family gathering → assign to a family/holiday story
#   Photo 4 (NDSU weight room) → training/discipline → assign to a martial arts story
#   Photo 5 (David and Nancy wedding) → love/beginnings → assign to courtship story

# Map Glen's audio to Gi Lee stories by spreading across chapters:
#   photo_2_8815fe43.wav → childhood story (Gi telling about family)
#   photo_3_6e739206.wav → adolescence story (family gathering)
#   photo_4_1b3ad267.wav → young adult story (training)
#   photo_5_11de68a4.wav → adult story (friends/allies)
#   story_polly-waveshare_1773008078.wav → reflection story (longest recording)


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Get Gi Lee's user_id
    cur.execute("SELECT id FROM user_profiles WHERE tenant_id=?", (GI_TENANT,))
    gi_user = cur.fetchone()
    gi_user_id = gi_user[0] if gi_user else None
    print(f"Gi Lee user_id: {gi_user_id}")

    # ── Step 1: Copy photo records into Gi Lee's tenant ──
    # We reuse the same image files on disk — just create new DB records
    glen_photos = [
        # (glen_photo_id, caption_for_gi, tags_for_gi, date_for_gi)
        (2, "Lily at her first gymnastics meet", '["Lily", "gymnastics", "dojo"]', "1998"),
        (3, "The whole Lee family at the coast — summer tradition", '["Lee family", "coast", "reunion"]', "2005"),
        (4, "Pacific Way Dojo — early morning training session", '["Pacific Way Dojo", "martial arts", "training"]', "1992"),
        (5, "Sarah and Gi at Ray's restaurant after the Portland tournament", '["Sarah", "Gi", "Ray Tanaka", "Portland"]', "1988"),
    ]

    gi_photo_ids = {}  # glen_photo_id → new gi_photo_id
    for glen_pid, caption, tags, date_taken in glen_photos:
        # Get the filename from Glen's photo
        cur.execute("SELECT filename FROM photos WHERE id=?", (glen_pid,))
        row = cur.fetchone()
        if not row:
            print(f"  Photo {glen_pid} not found, skipping")
            continue

        filename = row[0]

        # Check if we already created this photo for Gi
        cur.execute("SELECT id FROM photos WHERE tenant_id=? AND filename=?", (GI_TENANT, filename))
        existing = cur.fetchone()
        if existing:
            gi_photo_ids[glen_pid] = existing[0]
            print(f"  Photo {glen_pid} already exists as Gi photo {existing[0]}")
            continue

        cur.execute("""INSERT INTO photos
            (user_id, filename, original_name, caption, date_taken, tags, uploaded_by, tenant_id)
            VALUES (?,?,?,?,?,?,?,?)""",
            (gi_user_id, filename, f"gi_lee_demo_{glen_pid}.jpeg", caption, date_taken, tags, "demo", GI_TENANT))
        gi_photo_ids[glen_pid] = cur.lastrowid
        print(f"  Created Gi photo {cur.lastrowid} from Glen photo {glen_pid}: {caption}")

    conn.commit()
    print(f"\nCreated {len(gi_photo_ids)} photos for Gi Lee")

    # ── Step 2: Assign real audio + photos to Gi Lee stories ──
    # Spread across chapters for variety
    assignments = [
        # (gi_story_id, audio_file, glen_photo_id_to_link, reason)
        (23, "photo_2_8815fe43.wav", 2, "Ch1: Gi's childhood morning story + Lily photo"),
        (28, "photo_3_6e739206.wav", 3, "Ch2: Sarah's cooking story + family gathering photo"),
        (44, "photo_4_1b3ad267.wav", 4, "Ch4: Ray Tanaka tournament + training photo"),
        (54, "photo_5_11de68a4.wav", 5, "Ch6: Mike Santos walks in + friends photo"),
        (75, "story_polly-waveshare_1773008078.wav", None, "Ch10: Wisdom reflection + longest audio"),
        # Keep some stories with just audio, no photo
        (24, "photo_2_8815fe43.wav", None, "Ch1: Grandmother's kitchen"),
        (35, "photo_3_6e739206.wav", None, "Ch3: Grandfather Wei immigration"),
        (58, "photo_4_1b3ad267.wav", None, "Ch7: Lily on the mat"),
        (60, "photo_5_11de68a4.wav", None, "Ch8: Marcus and the guitar"),
        (66, "story_polly-waveshare_1773008078.wav", None, "Ch9: Transformation"),
    ]

    updated = 0
    for gi_story_id, audio_file, glen_photo_id, reason in assignments:
        # Check audio file exists
        audio_path = os.path.join(RECORDINGS_DIR, audio_file)
        if not os.path.exists(audio_path):
            print(f"  SKIP: {audio_file} not found on disk")
            continue

        # Get the Gi photo ID if linking a photo
        photo_id = gi_photo_ids.get(glen_photo_id) if glen_photo_id else None

        # Update the story
        if photo_id:
            cur.execute("""UPDATE stories
                SET audio_s3_key=?, qr_in_book=1, photo_id=?
                WHERE id=? AND tenant_id=?""",
                (audio_file, photo_id, gi_story_id, GI_TENANT))

            # Also link photo back to story
            cur.execute("UPDATE photos SET story_id=? WHERE id=?", (gi_story_id, photo_id))
        else:
            cur.execute("""UPDATE stories
                SET audio_s3_key=?, qr_in_book=1
                WHERE id=? AND tenant_id=?""",
                (audio_file, gi_story_id, GI_TENANT))

        updated += 1
        photo_note = f" + photo {photo_id}" if photo_id else ""
        print(f"  Story {gi_story_id}: {audio_file}{photo_note} — {reason}")

    conn.commit()
    print(f"\nUpdated {updated} stories with real audio/photos")

    # ── Step 3: Clean up old silent demo WAVs ──
    demo_files = [f for f in os.listdir(RECORDINGS_DIR) if f.startswith("demo_gi_lee_")]
    for f in demo_files:
        os.remove(os.path.join(RECORDINGS_DIR, f))
    print(f"Removed {len(demo_files)} placeholder WAV files")

    # ── Verify ──
    print("\n=== VERIFICATION ===")
    cur.execute("""SELECT s.id, s.speaker_name, s.audio_s3_key, s.photo_id, s.qr_in_book
        FROM stories s WHERE s.tenant_id=? AND s.audio_s3_key IS NOT NULL
        ORDER BY s.id""", (GI_TENANT,))
    for r in cur.fetchall():
        print(f"  Story {r[0]}: {r[1]} → audio={r[2]}, photo={r[3]}, qr={r[4]}")

    print("\n=== GI LEE PHOTOS ===")
    cur.execute("SELECT id, filename, caption, story_id FROM photos WHERE tenant_id=?", (GI_TENANT,))
    for r in cur.fetchall():
        print(f"  Photo {r[0]}: {r[2]} → story={r[3]}, file={r[1]}")

    conn.close()
    print("\nDone! QR codes now link to real voice recordings.")


if __name__ == "__main__":
    main()
