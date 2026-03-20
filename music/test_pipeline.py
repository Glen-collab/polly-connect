"""
test_pipeline.py
----------------
Run locally to validate the GPT prompt chain before wiring up ElevenLabs.
Uses generate_audio_file=False so it costs only GPT tokens, not EL credits.

Usage:
    OPENAI_API_KEY=sk-... python test_pipeline.py
"""

import json
from song_pipeline import chapter_to_song

# ── Sample chapter — replace with real Polly output ──────────────────────────
SAMPLE_CHAPTER = """
Chapter 4: The Summer She Moved to Chicago

Ruth had spent her whole life in Medford, Wisconsin — forty-two miles of county roads 
and the same faces at the same church every Sunday. But the summer of 1962 changed that.

Her sister Joanne had moved to Chicago three years earlier for secretarial work, and every 
letter she sent back smelled of perfume and possibility. Ruth had read them all twice, 
sometimes three times, on the back porch after supper when the fireflies were starting.

The day she told her father she was leaving, he didn't look up from his workbench. 
"You'll be back," he said. He wasn't cruel about it — just certain, the way farmers 
are certain about rain. 

She took the Greyhound on a Tuesday morning with one suitcase and forty-three dollars. 
The city hit her like a wall of sound when she stepped off at the terminal. She stood 
on the sidewalk for ten minutes, just breathing it in — diesel, coffee, newspaper ink, 
and something underneath all of it she couldn't name. Freedom, maybe. Or just the smell 
of a million people living fast.

Joanne had a couch for her and a job lead at Marshall Field's. Ruth took the job. 
She learned to navigate the L-train in a week. Within a month she had stopped 
flinching at car horns.
"""

if __name__ == "__main__":
    result = chapter_to_song(
        chapter_text=SAMPLE_CHAPTER,
        chapter_title="Chapter 4: The Summer She Moved to Chicago",
        person_name="Ruth Elaine Kowalski",
        genre_preference="auto",          # let GPT pick based on 1962 + emotion
        generate_audio_file=False,        # flip to True when EL key is ready
    )

    print("\n" + "═" * 60)
    print(f"  🎵  {result['song_title']}")
    print(f"  Genre: {result['genre']}")
    print(f"  Arc Stage: {result['jungian_stage']}")
    print(f"  Style Prompt: {result['style_prompt']}")
    print("═" * 60)

    lyrics = result["lyrics"]
    sections = ["verse1", "chorus", "verse2", "bridge", "outro"]
    labels = ["Verse 1", "Chorus", "Verse 2", "Bridge", "Outro"]
    for key, label in zip(sections, labels):
        print(f"\n[{label}]")
        print(lyrics[key])

    print("\n── Song Brief (debug) ──────────────────────────────────────")
    brief = result["song_brief"]
    print(f"Core emotion : {brief['essence']['core_emotion']}")
    print(f"Key imagery  : {', '.join(brief['essence']['key_imagery'])}")
    print(f"Era          : {brief['essence']['decade_or_era']}")
    print(f"Turning point: {brief['essence']['turning_point']}")
    print(f"Arc note     : {brief['stage_result']['explanation']}")
    print(f"Lyric notes  : {brief['lyrics_data']['lyric_notes']}")
