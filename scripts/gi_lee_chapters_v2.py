#!/usr/bin/env python3
"""Generate expanded Legacy Book chapters for Gi Lee — KDP-ready, 50-75 pages.
Run one chapter at a time: python3.11 scripts/gi_lee_chapters_v2.py <chapter_num>
"""
import sqlite3
import json
import sys
import os

DB_PATH = "polly.db"
TENANT_ID = 2

# Expanded chapters — each with section subheadings like "Dark Before The Dawn"
CHAPTERS = [
    (1, "Where It All Started",
     "ordinary_world", "childhood",
     ["The Fog Before Dawn", "Portsmouth Square", "The Golden Crane", "A World Within a World"],
     """This chapter opens Gi Lee's story in 1960s San Francisco Chinatown. Write about:
- The fog of early morning walks to Portsmouth Square with Grandfather Wei for tai chi
- The Golden Crane restaurant as the family anchor — Wei's immigrant story, the regulars, the corner table
- The sounds and smells of Chinatown — fish market, herbalist, bakery, the alley behind the restaurant
- Grandmother Mei-Hua's kitchen, the congee, the dumplings, the erhu music in the evenings
- The neighborhood that raised him — every shopkeeper knowing his name, no secrets in Chinatown
- Mr. Brush the calligrapher painting with water in the park — "the beauty is in the doing"
Use ALL the childhood/ordinary world memories. Each section subheading starts a new thematic thread within the chapter."""),

    (2, "The Kitchen Table",
     "ordinary_world", "childhood",
     ["Rice Porridge and Radio Dramas", "The Flashlight Holder", "Fabric Forts", "The Coin in the Dumpling"],
     """This chapter focuses on the intimate domestic life of the Lee family. Write about:
- Grandmother's kitchen — the congee ritual, nothing wasted, teaching Gi to roll dumplings
- Mother Lian's sewing room — the hum of the machine, Cantonese radio, Gi doing homework on the floor
- Father James (Jin) in the garage — Gi holding the flashlight, learning patience and precision
- The hidden coin in the New Year dumpling — Grandmother cheating for Gi every year
- Sarah making the congee recipe years later — seeing the little boy in the man
- How these domestic rhythms became the foundation for Gi's discipline
Each section should be 600-900 words with vivid sensory detail."""),

    (3, "Characters and Chinatown",
     "ordinary_world", "childhood",
     ["Uncle David and the Judo Stories", "Aunt Rose's Butterscotch", "Grandfather's Corner Table", "The Alley Behind the Golden Crane"],
     """This chapter introduces the colorful family characters who shaped Gi. Write about:
- Uncle David traveling to Japan for judo — the family rebel, the stories at dinner, the phrase that changed everything: "martial arts is not about fighting, it's about becoming someone worth being"
- Aunt Rose the peacemaker — butterscotch candy, managing the family dynamics like a classroom
- Grandfather Wei reading the room at the Golden Crane — "every person who walks through that door has a story"
- Tommy Lee — racing bikes through Chinatown alleys, the homemade sparring gear, the rivalry and brotherhood
- Grandmother's herbal remedies — ginger tea, dried longan, "healing starts with believing you can heal"
- Wei's immigration story — seventeen dollars, the laundry shop, the Everyone Welcome sign
Each section 600-900 words, written like a memoir with specific dialogue and moments."""),

    (4, "When Things Changed",
     "call_to_adventure", "adolescence",
     ["Horse Stance", "The Restaurant Kitchen", "The Black Eye", "Northern California"],
     """This is the call to adventure — when Gi found martial arts. Write about:
- First day at Master Chen's dojo at age 12 — the humbling horse stance, "now you know where you begin"
- Working at Grandfather's restaurant after school — dishes, prep, cooking — earning your way up
- Master Chen's floor-sweeping rule — "the floor does not care what color your belt is"
- Lian's reaction to Gi's black eye — "Mama, I earned this"
- Meeting Ray Tanaka at the Oakland tournament at 16 — "I do not fight. I solve problems."
- The moment of decision at 17 — winning the championship, noodles with father, "I see that it makes you someone"
- Father sitting in the car at Master Chen's dojo every week for six years without saying "I support you"
- Choosing martial arts over trade school — father sitting in the garage for two hours
Each section 700-1000 words. This chapter should feel like a turning point."""),

    (5, "Stepping Out",
     "call_to_adventure", "adolescence",
     ["Saturday Afternoons with Bruce Lee", "The Competition", "The Rule Follower", "Two Perfectly Good Boys"],
     """This chapter explores Gi's adolescent identity forming. Write about:
- Bruce Lee movies with Uncle David and Tommy — VCR, popcorn, breaking down techniques, "be water my friend"
- The tournament circuit with Ray — traveling, competing, growing together
- Tommy and Gi sneaking into the movie theater — getting caught, Gi buying proper tickets the next week
- Father at Stinson Beach — the one place he fully relaxed, "two perfectly good boys wasting energy on nonsense"
- Chinese New Year as a teenager — the firecrackers, father reframing fear as protection
- Moon Festival on the rooftop, summer coastal trips, the blending of two cultures
- The growing sense that martial arts was not a hobby but an identity
Each section 600-900 words with the warmth of family and the intensity of self-discovery."""),

    (6, "Love and Beginnings",
     "crossing_threshold", "young_adult",
     ["The Girl with the Book", "Plum Wine and First Impressions", "The Bamboo Bends", "Thirty-One Days"],
     """The crossing of the threshold — love, leaving home, opening the dojo. Write about:
- Meeting Sarah at the Portland tournament — she was reading a book during the fights, "something worth more than what is happening out there"
- Meeting Sarah's parents — "I teach people how to fight. Mostly I teach them how not to."
- Moving to Portland at 27 — leaving Chinatown, leaving Master Chen, the two suitcases, hearing Grandfather's voice: "the bamboo that does not bend will break"
- Proposing on the Hawthorne Bridge — "I cannot promise you an easy life but I can promise you an honest one"
- Opening Pacific Way Dojo — the warehouse on Division Street, sanding the floor, used mats, Sarah grading papers at the empty desk
- Mike Santos walking in on day 31 — the angry teenager, "What are you angry about?" "Everything." "Good. Anger means you care."
- The terrifying first year of a small business owner
Each section 700-1000 words. This chapter should feel like stepping into the unknown with love as the anchor."""),

    (7, "The Hard Years",
     "trials_allies_enemies", "adult",
     ["Lily on the Mat", "Bottles and Katas", "The Gibson Guitar", "Two Blocks Away"],
     """The trials of building a family and a dojo simultaneously. Write about:
- Lily at age 5 on the dojo mat — "Mama, I am not fighting. I am dancing."
- The twins arriving — three kids under three, 3 AM feedings, Sarah's difficult delivery, Gi holding both babies saying "this is just another form"
- Marcus choosing music over martial arts — the arguments, Sarah saying "you are being exactly like your father"
- The Gibson guitar Christmas gift — "every discipline is the same discipline. Your music is your dojo." Marcus crying.
- The rival dojo opening two blocks away — losing students, bleeding knuckles on the heavy bag at 4 AM, Sarah wrapping his hands
- Twelve years later the rival closed. Pacific Way is still here.
- Learning that children are not extensions of you — Master Chen's lesson: "the best teacher creates originals"
Each section 700-1000 words. This chapter should feel like being tested from every direction."""),

    (8, "Who Stood By Me",
     "trials_allies_enemies", "adult",
     ["Sarah's Quiet Strength", "Saturday Morning Ramen", "The First Student", "Mrs. Patterson's Groceries"],
     """The allies and companions who held Gi up. Write about:
- Sarah — bringing lunch to the empty dojo, grading papers at the desk, never once suggesting he quit, wrapping his bleeding hands
- Ray Tanaka — 49 years of friendship, Saturday morning sparring then ramen at Tanaka's shop, the kind of friend who sees you cry and never tells anyone
- Mike Santos — from troubled 16-year-old to running his own dojo in Seattle, calling to say "thank you for seeing me when nobody else did"
- Mrs. Patterson — the elderly neighbor in Portland, Thursday groceries, "you are doing exactly what you are supposed to be doing"
- Tom Chen — Sarah's brother, the firefighter, terrible jokes and incredible tri-tip, the steady anchor
- Daniel becoming a physical therapist — inheriting the healing side of martial arts
- Thanksgiving chaos — the whole family together, Gi stepping outside to thank the absent ones
Each section 600-900 words. This chapter should feel warm and grateful."""),

    (9, "How I Changed",
     "transformation", "midlife",
     ["One Inch", "The Brush and the Fist", "The Empty Dojo", "The Form in the Dark"],
     """The transformation chapter — injuries, loss, and becoming someone new. Write about:
- The ACL tear at 35 — one inch off on a landing, the pop, 4 months recovery, standing forms from a chair then crutches
- The hand nerve injury — partial numbness, unable to make a fist, taking up calligraphy, Mr. Brush's lesson returning
- Two years of painting — "from a fighter who used his hands to hurt, to a man who used his hands to create"
- Master Chen's death in 2000 — flying back to SF, standing in horse stance in the empty dojo for one hour, hearing his voice
- The transformation from Fighter Gi to Teacher Gi — the identity graveyard, the old selves dying
- Grandfather Wei's bamboo lesson in full — the typhoons, bending but not breaking, the philosophy that runs through everything
- The 4 AM practice as church — "connected to every person who has ever stood in a dojo and decided to show up"
Each section 700-1000 words. This is the emotional heart of the book."""),

    (10, "What I Know Now",
     "return_with_knowledge", "reflection",
     ["Discipline Is Freedom", "The Strongest Man in the Room", "Forty Years of Teaching", "Be Still"],
     """The return with knowledge — wisdom and legacy. Write about:
- "Discipline is not punishment. It is freedom." — the 4 AM dojo as sacred space, parallel to Grandfather Wei's dawn tai chi
- Teaching Mike Santos — "I gave him a container for all that energy"
- "The strongest man in the room is not the one who can break things. It is the one who can hold things together."
- Forty years of teaching — thousands of students, each one teaching Gi something back
- "The fist reveals the heart. And teaching reveals the teacher." — Master Chen's final lesson
- Marcus's jazz show — "every discipline is the same discipline"
- Ray's observation: "the discipline is not armor. It is how he channels the caring into something useful."
- Sarah after 41 years: "He is not a perfect man. He is a present man."
- The closing meditation — "Be still. Pay attention. Show up. The rest takes care of itself."
- What Gi wants his grandchildren to know
Each section 700-1000 words. This chapter should close the arc with earned wisdom and quiet power."""),
]


def get_memories_for_chapter(cur, bucket, life_phase):
    """Get memories matching this chapter's bucket and life phase."""
    cur.execute("""
        SELECT id, speaker, text, text_summary, people, locations
        FROM memories WHERE tenant_id=? AND bucket=? AND life_phase=?
        ORDER BY id
    """, (TENANT_ID, bucket, life_phase))
    return cur.fetchall()


def generate_chapter(ch_num, title, bucket, life_phase, sections, description, memories, client):
    """Use GPT to generate an expanded chapter draft with section subheadings."""
    memory_texts = []
    for i, mem in enumerate(memories, 1):
        mid, speaker, text, summary, people, locations = mem
        entry = f"Memory {i} (told by {speaker}): {text}"
        memory_texts.append(entry)

    sections_str = "\n".join(f"- {s}" for s in sections)

    prompt = f"""You are writing Chapter {ch_num} of a published family legacy memoir called "The Story of Gi Lee."
This is a REAL BOOK being printed through KDP at 6x9 inches. It needs to read like a professional memoir — think Mitch Albom's "Tuesdays with Morrie" or a well-crafted family history.

Chapter title: "{title}"
Jungian arc stage: {bucket.replace('_', ' ')}
Life phase: {life_phase}

SECTION SUBHEADINGS (use these as section breaks within the chapter, like a published book):
{sections_str}

DIRECTION:
{description}

FAMILY MEMORIES TO WEAVE IN (use ALL of them — expand on them, add transitions, add scene-setting):
{chr(10).join(memory_texts)}

CRITICAL WRITING REQUIREMENTS:
1. LENGTH: Write 2,500-3,500 words. This is a FULL book chapter, not a summary.
2. SECTION BREAKS: Use each section subheading as a bold section header. Each section should be 600-900 words.
3. STYLE: Write in third person about Gi (he/him). Warm, literary, honest tone. Blue-collar poetry.
4. SENSORY DETAIL: Smells, sounds, textures, weather, light. Make the reader feel they are there.
5. DIALOGUE: Include natural spoken dialogue (in quotes) from the family members. Not every memory needs quotes, but key moments should have them.
6. PACING: Vary sentence length. Short punchy sentences for impact. Longer flowing ones for reflection.
7. SCENE-SETTING: Each section opens with a vivid image or moment before expanding into the broader story.
8. REFLECTION: Weave Gi's current-day reflections between the memories. He is looking back with wisdom.
9. TRANSITIONS: Smooth transitions between memories and sections. No abrupt jumps.
10. NO MARKDOWN: Do not use # headers or ** bold or any markdown. Write section headings as plain text on their own line, ALL CAPS or Title Case. Separate sections with a blank line.
11. FIRST PARAGRAPH: After each section heading, the first paragraph should NOT be indented (this is standard book formatting).

IMPORTANT: This chapter MUST be at least 2,500 words. Each of the 4 sections must be at least 600 words. Do NOT summarize — EXPAND. Add scene-setting, sensory details, internal thoughts, and reflections. This is a FULL memoir chapter, not a blog post.

Write the full chapter now:"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=16000,
        temperature=0.85,
    )
    return response.choices[0].message.content.strip()


def main():
    from openai import OpenAI

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

    if len(sys.argv) < 2:
        print("Usage: python3.11 scripts/gi_lee_chapters_v2.py <chapter_num>")
        print("Chapters 1-10 available")
        return

    target = int(sys.argv[1])

    for ch_num, title, bucket, life_phase, sections, desc in CHAPTERS:
        if ch_num != target:
            continue

        memories = get_memories_for_chapter(cur, bucket, life_phase)
        if not memories:
            print(f"  Chapter {ch_num}: No memories for {bucket}/{life_phase}, skipping")
            continue

        print(f"Generating Chapter {ch_num}: {title} ({len(memories)} memories, target ~3000 words)...")
        content = generate_chapter(ch_num, title, bucket, life_phase, sections, desc, memories, client)

        if content:
            word_count = len(content.split())
            memory_ids = json.dumps([m[0] for m in memories])

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
            print(f"  Saved! ({len(content)} chars, ~{word_count} words)")
        else:
            print(f"  FAILED to generate chapter {ch_num}")

    conn.close()
    print("Done!")


if __name__ == "__main__":
    main()
