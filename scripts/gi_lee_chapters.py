#!/usr/bin/env python3
"""Generate Legacy Book chapter drafts for Gi Lee, one at a time."""
import sqlite3
import json
import sys
import os

# Add server to path for OpenAI
sys.path.insert(0, "/opt/polly-connect")

DB_PATH = "polly.db"
TENANT_ID = 2

# Chapter templates matching the Jungian arc
CHAPTERS = [
    (1, "Where It All Started", "ordinary_world", "childhood",
     "Childhood memories of Chinatown, the Golden Crane restaurant, Grandfather Wei's morning tai chi, and the kitchen that was the heart of the Lee family."),
    (2, "The Kitchen Table", "ordinary_world", "childhood",
     "The family kitchen and sewing room — Grandmother Mei-Hua's cooking, Mother Lian's tailoring, and the rhythms of daily life in a Chinese American household."),
    (3, "Characters and Chinatown", "ordinary_world", "childhood",
     "The colorful characters who shaped young Gi — Uncle David's judo stories, Aunt Rose's butterscotch candy, Cousin Tommy's rivalry, and the neighborhood that raised him."),
    (4, "When Things Changed", "call_to_adventure", "adolescence",
     "The call to martial arts — Master Chen's dojo, the first humbling lesson, working at the Golden Crane, and the decision that changed everything."),
    (5, "Stepping Out", "call_to_adventure", "adolescence",
     "Growing into a martial artist — meeting Ray Tanaka, winning the first championship, earning Father's quiet respect, and finding identity through discipline."),
    (6, "Love and Beginnings", "crossing_threshold", "young_adult",
     "Meeting Sarah Chen in Portland, leaving San Francisco behind, opening Pacific Way Dojo, and the terrifying first month when nobody came — until Mike Santos walked through the door."),
    (7, "The Hard Years", "trials_allies_enemies", "adult",
     "Building a family and a dojo — Lily's natural talent, the twins' arrival, Marcus choosing music over martial arts, and the rival school that tested everything."),
    (8, "Who Stood By Me", "trials_allies_enemies", "adult",
     "The people who held Gi up — Sarah's quiet strength, Ray's lifelong friendship, and the lessons learned from raising three very different children."),
    (9, "How I Changed", "transformation", "midlife",
     "The knee injury that nearly ended everything, the hand injury that led to calligraphy, losing Master Chen, and the transformation from fighter to teacher."),
    (10, "What I Know Now", "return_with_knowledge", "reflection",
     "The wisdom distilled from six decades — discipline as freedom, the 4 AM practice, teaching Mike Santos, and the lessons Gi wants his grandchildren to carry forward."),
]


def get_memories_for_chapter(cur, bucket, life_phase):
    """Get memories matching this chapter's bucket and life phase."""
    cur.execute("""
        SELECT id, speaker, text, text_summary, people, locations
        FROM memories WHERE tenant_id=? AND bucket=? AND life_phase=?
        ORDER BY id
    """, (TENANT_ID, bucket, life_phase))
    return cur.fetchall()


def generate_chapter(chapter_num, title, bucket, life_phase, description, memories, client):
    """Use GPT to generate a chapter draft."""
    memory_texts = []
    for i, mem in enumerate(memories, 1):
        mid, speaker, text, summary, people, locations = mem
        entry = f"Memory {i} (told by {speaker}): {text}"
        memory_texts.append(entry)

    prompt = f"""You are writing Chapter {chapter_num} of a family legacy book called "The Story of Gi Lee."

Chapter title: "{title}"
Chapter theme: {description}
Jungian arc stage: {bucket.replace('_', ' ')}
Life phase: {life_phase}

Here are the family memories to weave into this chapter:

{chr(10).join(memory_texts)}

Write a warm, narrative chapter (8-12 paragraphs) that:
- Weaves ALL of these memories into a cohesive, flowing story
- Preserves each speaker's voice and perspective when quoting them
- Opens with a vivid scene-setting paragraph
- Uses smooth transitions between memories
- Builds emotional momentum throughout the chapter
- Closes with a reflective paragraph that connects to the broader life journey
- Maintains a blue-collar, honest, heartfelt tone throughout
- Writes in third person about Gi (he/his), not first person
- Includes specific sensory details (smells, sounds, textures)
- Does NOT use quotation marks for thoughts — use italics or paraphrase
- Feels like a chapter from a published memoir, not a summary

Write the full chapter now:"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=3000,
        temperature=0.8,
    )
    return response.choices[0].message.content.strip()


def main():
    from openai import OpenAI

    # Load API key from .env
    env_path = "/opt/polly-connect/.env"
    api_key = None
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("OPENAI_API_KEY="):
                    api_key = line.strip().split("=", 1)[1].strip('"').strip("'")
    if not api_key:
        print("ERROR: No OPENAI_API_KEY found in .env")
        return

    client = OpenAI(api_key=api_key)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Check which chapters to generate
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    end = int(sys.argv[2]) if len(sys.argv) > 2 else start

    for ch_num, title, bucket, life_phase, desc in CHAPTERS:
        if ch_num < start or ch_num > end:
            continue

        memories = get_memories_for_chapter(cur, bucket, life_phase)
        if not memories:
            print(f"  Chapter {ch_num}: No memories for {bucket}/{life_phase}, skipping")
            continue

        print(f"Generating Chapter {ch_num}: {title} ({len(memories)} memories)...")
        content = generate_chapter(ch_num, title, bucket, life_phase, desc, memories, client)

        if content:
            # Save to chapter_drafts
            memory_ids = json.dumps([m[0] for m in memories])

            # Check if draft exists
            cur.execute("SELECT id FROM chapter_drafts WHERE chapter_number=? AND tenant_id=?",
                        (ch_num, TENANT_ID))
            existing = cur.fetchone()
            if existing:
                cur.execute("""UPDATE chapter_drafts SET title=?, content=?, bucket=?, life_phase=?,
                    memory_ids=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (title, content, bucket, life_phase, memory_ids, existing[0]))
            else:
                cur.execute("""INSERT INTO chapter_drafts
                    (chapter_number, title, bucket, life_phase, memory_ids, content, status, tenant_id)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (ch_num, title, bucket, life_phase, memory_ids, content, "draft", TENANT_ID))

            conn.commit()
            print(f"  Saved! ({len(content)} chars)")
        else:
            print(f"  FAILED to generate chapter {ch_num}")

    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
