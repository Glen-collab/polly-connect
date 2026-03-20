"""
song_pipeline.py
----------------
Polly Connect — Chapter-to-Song Pipeline
Converts a biographical chapter (Jungian arc) into a full song brief,
then optionally generates audio via ElevenLabs or Suno Music API.

Phase 1: GPT lyrics/brief generation (costs only GPT tokens)
Phase 2: Audio generation (costs API credits, Legacy tier only)
"""

import os
import json
import logging

logger = logging.getLogger(__name__)

# Lazy-load clients
_openai_client = None
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")


def _get_openai():
    global _openai_client
    if _openai_client is None:
        try:
            from openai import OpenAI
            _openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
        except ImportError:
            logger.error("openai package not installed")
            return None
    return _openai_client

# ── Jungian Stage Definitions ─────────────────────────────────────────────────
# Maps each arc stage to musical guidance so the style prompt stays emotionally true.
JUNGIAN_MUSIC_MAP = {
    "ordinary_world":       {"mood": "nostalgic, warm, grounded",       "energy": "low-mid", "song_role": "verse foundation"},
    "call_to_adventure":    {"mood": "curious, hopeful, restless",       "energy": "building","song_role": "pre-chorus tension"},
    "refusal_of_call":      {"mood": "hesitant, melancholic, uncertain", "energy": "low",     "song_role": "minor-key verse"},
    "meeting_the_mentor":   {"mood": "grateful, reverent, inspired",     "energy": "mid",     "song_role": "bridge or key verse"},
    "crossing_threshold":   {"mood": "bold, determined, bittersweet",    "energy": "rising",  "song_role": "chorus entry"},
    "tests_allies_enemies": {"mood": "tense, dramatic, persevering",     "energy": "mid-high","song_role": "verse/bridge conflict"},
    "ordeal":               {"mood": "raw, emotional, breaking-point",   "energy": "peak",    "song_role": "emotional bridge"},
    "reward":               {"mood": "triumphant, relieved, grateful",   "energy": "high",    "song_role": "power chorus"},
    "road_back":            {"mood": "reflective, wistful, determined",  "energy": "easing",  "song_role": "final verse"},
    "resurrection":         {"mood": "transcendent, cathartic, soaring", "energy": "climax",  "song_role": "final chorus"},
    "return_with_elixir":   {"mood": "peaceful, wise, complete",         "energy": "gentle",  "song_role": "outro / resolution"},
}

# ── Step 1: Detect Jungian Stage ──────────────────────────────────────────────
def detect_jungian_stage(chapter_text: str) -> dict:
    """
    Ask GPT to identify which Jungian hero arc stage this chapter represents.
    Returns the stage key + a short explanation.
    """
    stages = list(JUNGIAN_MUSIC_MAP.keys())
    prompt = f"""
You are analyzing a biographical chapter written using the Jungian hero's journey arc.

Chapter text:
\"\"\"
{chapter_text[:3000]}
\"\"\"

Identify which single stage of the hero's journey this chapter primarily represents.
Choose from this exact list:
{json.dumps(stages, indent=2)}

Respond ONLY with valid JSON in this format:
{{
  "stage": "<stage_key>",
  "explanation": "<one sentence why>"
}}
"""
    response = _get_openai().chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    return json.loads(response.choices[0].message.content)


# ── Step 2: Extract Story Essence ─────────────────────────────────────────────
def extract_chapter_essence(chapter_text: str, chapter_title: str, person_name: str) -> dict:
    """
    Pull the emotional core, key imagery, era, and themes from a chapter.
    This feeds directly into lyric and style prompt generation.
    """
    prompt = f"""
You are a songwriter and biographer. Extract the emotional essence from this life chapter
about {person_name}, titled "{chapter_title}".

Chapter text:
\"\"\"
{chapter_text[:3000]}
\"\"\"

Respond ONLY with valid JSON:
{{
  "core_emotion": "<primary emotion — e.g. 'grief and resilience'>",
  "key_imagery": ["<2-4 vivid images or metaphors from the text>"],
  "decade_or_era": "<estimated decade this memory is from, e.g. '1960s', 'early 1980s'>",
  "people_mentioned": ["<names of significant people in this chapter>"],
  "turning_point": "<one sentence describing the pivotal moment in this chapter>",
  "theme_words": ["<4-6 single words capturing the themes, e.g. 'loss', 'hope', 'family'>"]
}}
"""
    response = _get_openai().chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.4,
    )
    return json.loads(response.choices[0].message.content)


# ── Step 3: Generate Lyrics ───────────────────────────────────────────────────
def generate_lyrics(
    essence: dict,
    stage_info: dict,
    music_guidance: dict,
    person_name: str,
    genre_preference: str = "auto",
) -> dict:
    """
    Write full song lyrics (verse/chorus/bridge) grounded in the chapter's
    emotional truth. Genre can be user-selected or auto-detected from the era.
    """
    genre_instruction = (
        f"The user wants the genre to be: {genre_preference}."
        if genre_preference != "auto"
        else f"Auto-select a genre that fits the era ({essence.get('decade_or_era', 'unknown')}) "
             f"and mood ({music_guidance['mood']}). Consider: folk, soul, country, rock, gospel, "
             f"R&B, blues, or pop depending on era and emotion."
    )

    prompt = f"""
You are a professional songwriter writing a deeply personal song about a real person's life chapter.

Person: {person_name}
Chapter turning point: {essence['turning_point']}
Core emotion: {essence['core_emotion']}
Key imagery: {', '.join(essence['key_imagery'])}
Theme words: {', '.join(essence['theme_words'])}
Hero arc stage: {stage_info['stage']} — {stage_info['explanation']}
Musical mood: {music_guidance['mood']}
Energy: {music_guidance['energy']}
{genre_instruction}

Write a complete song with this structure:
- [Verse 1]: Set the scene. Ground the listener in the specific memory.
- [Chorus]: The emotional truth — universal enough to resonate, personal enough to feel true.
- [Verse 2]: Deepen the story. Show the cost or the discovery.
- [Bridge]: The shift — the moment everything changes. Matches the arc stage.
- [Chorus]: Repeat with new emotional weight.
- [Outro]: Resolution. Where they land after this chapter.

Guidelines:
- Write in second person ("you") to honor the subject without being presumptuous
- Use concrete imagery from the essence data, not abstract platitudes
- Each section 4-6 lines
- Chorus should be memorable, singable, emotionally resonant

Respond ONLY with valid JSON:
{{
  "song_title": "<evocative title>",
  "genre": "<chosen genre>",
  "lyrics": {{
    "verse1": "<lyrics>",
    "chorus": "<lyrics>",
    "verse2": "<lyrics>",
    "bridge": "<lyrics>",
    "outro": "<lyrics>"
  }},
  "lyric_notes": "<brief note on creative choices made>"
}}
"""
    response = _get_openai().chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.8,
    )
    return json.loads(response.choices[0].message.content)


# ── Step 4: Build ElevenLabs Style Prompt ─────────────────────────────────────
def build_style_prompt(essence: dict, lyrics_data: dict, music_guidance: dict) -> str:
    """
    Constructs the style/prompt string for ElevenLabs Music generation.
    ElevenLabs accepts a natural language descriptor alongside the lyrics.
    """
    genre = lyrics_data["genre"]
    mood = music_guidance["mood"]
    era = essence.get("decade_or_era", "timeless")
    energy = music_guidance["energy"]
    imagery = essence["key_imagery"][0] if essence["key_imagery"] else ""

    return (
        f"{genre}, {era} sound, {mood}, {energy} energy, "
        f"emotionally resonant vocals, organic instrumentation, "
        f"cinematic storytelling feel. Inspired by: {imagery}."
    )


# ── Step 5: Generate Audio via ElevenLabs ────────────────────────────────────
def generate_audio(lyrics_data: dict, style_prompt: str) -> bytes | None:
    """
    Calls ElevenLabs Music API with the lyrics + style prompt.
    Returns raw audio bytes (MP3).

    ElevenLabs Music API endpoint as of 2025:
    POST https://api.elevenlabs.io/v1/sound-generation  (for music)
    or   https://api.elevenlabs.io/v1/music/generate    (check current docs)
    """
    # Flatten lyrics into a single string for the prompt
    lyrics = lyrics_data["lyrics"]
    full_lyrics = "\n\n".join([
        f"[Verse 1]\n{lyrics['verse1']}",
        f"[Chorus]\n{lyrics['chorus']}",
        f"[Verse 2]\n{lyrics['verse2']}",
        f"[Bridge]\n{lyrics['bridge']}",
        f"[Chorus]\n{lyrics['chorus']}",
        f"[Outro]\n{lyrics['outro']}",
    ])

    payload = {
        "text": full_lyrics,
        "style": style_prompt,
        "output_format": "mp3_44100_128",
    }

    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }

    if not ELEVENLABS_API_KEY:
        logger.warning("ELEVENLABS_API_KEY not set — skipping audio generation")
        return None

    # NOTE: Verify the exact endpoint in ElevenLabs docs — they updated it in late 2025
    import requests
    try:
        response = requests.post(
            "https://api.elevenlabs.io/v1/music/generate",
            json=payload,
            headers=headers,
            timeout=120,
        )
        response.raise_for_status()
        return response.content  # raw MP3 bytes
    except Exception as e:
        logger.error(f"ElevenLabs audio generation failed: {e}")
        return None


# ── Master Pipeline Function ──────────────────────────────────────────────────
def chapter_to_song(
    chapter_text: str,
    chapter_title: str,
    person_name: str,
    genre_preference: str = "auto",
    generate_audio_file: bool = True,
) -> dict:
    """
    Full pipeline: chapter text → song brief → (optional) audio file.

    Returns a dict with everything needed to display, save, or stream:
    {
        "song_title":    str,
        "genre":         str,
        "lyrics":        dict,
        "style_prompt":  str,
        "jungian_stage": str,
        "audio_bytes":   bytes | None,
        "song_brief":    dict   # full intermediate data for debugging/display
    }
    """
    print(f"[SongPipeline] Processing chapter: '{chapter_title}' for {person_name}")

    # Step 1 — Detect arc stage
    stage_result = detect_jungian_stage(chapter_text)
    stage_key = stage_result["stage"]
    music_guidance = JUNGIAN_MUSIC_MAP.get(stage_key, JUNGIAN_MUSIC_MAP["ordinary_world"])
    print(f"[SongPipeline] Arc stage: {stage_key}")

    # Step 2 — Extract essence
    essence = extract_chapter_essence(chapter_text, chapter_title, person_name)
    print(f"[SongPipeline] Core emotion: {essence['core_emotion']}")

    # Step 3 — Generate lyrics
    lyrics_data = generate_lyrics(essence, stage_result, music_guidance, person_name, genre_preference)
    print(f"[SongPipeline] Song title: '{lyrics_data['song_title']}' | Genre: {lyrics_data['genre']}")

    # Step 4 — Build style prompt
    style_prompt = build_style_prompt(essence, lyrics_data, music_guidance)
    print(f"[SongPipeline] Style prompt: {style_prompt}")

    # Step 5 — Generate audio (optional, costs API credits)
    audio_bytes = None
    if generate_audio_file:
        print("[SongPipeline] Calling ElevenLabs Music API...")
        audio_bytes = generate_audio(lyrics_data, style_prompt)
        print(f"[SongPipeline] Audio generated: {len(audio_bytes):,} bytes")

    return {
        "song_title":    lyrics_data["song_title"],
        "genre":         lyrics_data["genre"],
        "lyrics":        lyrics_data["lyrics"],
        "style_prompt":  style_prompt,
        "jungian_stage": stage_key,
        "audio_bytes":   audio_bytes,
        "song_brief": {
            "stage_result":    stage_result,
            "essence":         essence,
            "lyrics_data":     lyrics_data,
            "music_guidance":  music_guidance,
        },
    }


# ── Process Full Book ─────────────────────────────────────────────────────────
def book_to_album(
    chapters: list[dict],
    person_name: str,
    genre_preference: str = "auto",
    generate_audio_file: bool = True,
) -> list[dict]:
    """
    Process every chapter in a book and return a full album tracklist.

    chapters = [
        {"title": "Chapter 1: The Farm", "text": "..."},
        {"title": "Chapter 2: Leaving Home", "text": "..."},
        ...
    ]

    Returns list of song result dicts (same shape as chapter_to_song output),
    each with an added "track_number" field.
    """
    album = []
    for i, chapter in enumerate(chapters, start=1):
        print(f"\n[SongPipeline] === Track {i}/{len(chapters)}: {chapter['title']} ===")
        result = chapter_to_song(
            chapter_text=chapter["text"],
            chapter_title=chapter["title"],
            person_name=person_name,
            genre_preference=genre_preference,
            generate_audio_file=generate_audio_file,
        )
        result["track_number"] = i
        result["chapter_title"] = chapter["title"]
        album.append(result)
    return album
