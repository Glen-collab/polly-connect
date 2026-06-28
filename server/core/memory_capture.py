"""
Legacy Funnel — universal memory capture for Polly Connect.

Every surface (Chatter, Wall, Photos, recorded Stories) funnels into the ONE
`memories` table through this module, where book_builder picks it up. See
docs/POLLY_LEGACY_FUNNEL.md for the full blueprint.

Two cheap GPT passes (gpt-4o-mini), each one item at a time (never the whole
life at once):

  - score_and_classify(text)  → story-value 0..1 + Jungian bucket/life_phase/
                                 people/locations/emotions/summary/year
  - polly_interjection(thread) → Polly's warm, in-persona "2 cents" + 1-3
                                 follow-up questions + the same classification

capture(...) writes a `stories` row (raw archive) + a `memories` row tagged with
source / source_ref / story_value / include_in_book so the legacy book can draw
from it. Dedupes on (source, source_ref) so a post is never captured twice.

OpenAI only (consistent with the rest of Polly). Degrades gracefully to keyword
heuristics if OPENAI_API_KEY is missing — capture still works, just less smart.
"""

import json
import logging
import os
import sqlite3

logger = logging.getLogger(__name__)

# Story-value gate: anything at or above this auto-captures. The Polly button
# captures regardless (an explicit human invite always counts).
STORY_VALUE_THRESHOLD = 0.6

VALID_BUCKETS = {
    "ordinary_world", "call_to_adventure", "crossing_threshold",
    "trials_allies_enemies", "transformation", "return_with_knowledge",
}
VALID_PHASES = {
    "childhood", "adolescence", "young_adult", "adult",
    "midlife", "elder", "reflection", "unknown",
}

# Phrases that signal a memory is emerging — used for the heuristic fallback
# score and for the passive "tap Polly" nudge.
STORY_TRIGGERS = [
    "remember when", "i never told you", "the funniest thing", "back when",
    "used to", "when i was", "i'll never forget", "i will never forget",
    "the lesson", "our family always", "growing up", "the first time",
    "the day i", "the day we", "years ago", "when your", "your grandpa",
    "your grandma", "my mother", "my father", "when we were", "reminds me",
]


# ── OpenAI plumbing ──────────────────────────────────────────────────────

def _client():
    """Return an OpenAI client or None if unavailable."""
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=key)
    except Exception as e:  # pragma: no cover - import/runtime guard
        logger.warning("OpenAI client unavailable: %s", e)
        return None


def _chat_json(system: str, user: str, max_tokens: int = 700) -> dict:
    """One gpt-4o-mini JSON call. Raises on failure (callers fall back)."""
    client = _client()
    if client is None:
        raise RuntimeError("OPENAI_API_KEY not set")
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.5,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content.strip())


# ── Classification (the shared JSON shape every surface produces) ─────────

_CLASSIFY_SPEC = (
    '  "story_value": <0.0-1.0 — how much this belongs in a family legacy book; '
    "everyday chatter/logistics/complaints score low, real memories, lessons, "
    "milestones, feelings, and family history score high>,\n"
    '  "bucket": "<ordinary_world | call_to_adventure | crossing_threshold | '
    'trials_allies_enemies | transformation | return_with_knowledge>",\n'
    '  "life_phase": "<childhood | adolescence | young_adult | adult | midlife | '
    'elder | reflection | unknown>",\n'
    '  "estimated_year": <4-digit year mentioned, or null>,\n'
    '  "people": ["names mentioned"],\n'
    '  "locations": ["named places"],\n'
    '  "emotions": ["joy, love, nostalgia, sadness, fear, anger, pride, '
    'gratitude, humor, courage, peace, adventure"],\n'
    '  "summary": "<one-sentence summary, max 120 chars>"\n'
)

_BUCKET_GUIDE = (
    "Bucket guide (Jungian arc):\n"
    "- ordinary_world: everyday life, family, routines, home, before things changed\n"
    "- call_to_adventure: surprises, opportunities, turning points\n"
    "- crossing_threshold: decisions, leaving, starting over, first big step\n"
    "- trials_allies_enemies: hard times, struggles, who helped or hurt\n"
    "- transformation: how you changed, realized, grew\n"
    "- return_with_knowledge: wisdom, advice, what you'd tell someone now\n"
)


def _clean_classification(parsed: dict) -> dict:
    """Coerce a raw GPT dict into a safe, normalized classification."""
    try:
        sv = float(parsed.get("story_value"))
    except (TypeError, ValueError):
        sv = 0.5
    sv = max(0.0, min(1.0, sv))

    bucket = parsed.get("bucket") or "ordinary_world"
    if bucket not in VALID_BUCKETS:
        bucket = "ordinary_world"
    phase = parsed.get("life_phase") or "unknown"
    if phase not in VALID_PHASES:
        phase = "unknown"

    year = parsed.get("estimated_year")
    try:
        year = int(year) if year else None
    except (TypeError, ValueError):
        year = None

    def _list(v):
        return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []

    return {
        "story_value": sv,
        "bucket": bucket,
        "life_phase": phase,
        "estimated_year": year,
        "people": _list(parsed.get("people")),
        "locations": _list(parsed.get("locations")),
        "emotions": _list(parsed.get("emotions")),
        "summary": (str(parsed.get("summary") or "")[:120]).strip(),
    }


def _heuristic_classification(text: str) -> dict:
    """No-API fallback: score on story-trigger phrases + length."""
    low = (text or "").lower()
    hits = sum(1 for t in STORY_TRIGGERS if t in low)
    words = len(low.split())
    score = min(1.0, 0.25 + 0.18 * hits + min(0.25, words / 200.0))
    return {
        "story_value": round(score, 2),
        "bucket": "ordinary_world",
        "life_phase": "unknown",
        "estimated_year": None,
        "people": [],
        "locations": [],
        "emotions": [],
        "summary": (text or "").strip().split("\n")[0][:120],
    }


def score_and_classify(text: str, birth_year=None) -> dict:
    """Score story-value + classify a single item. Never raises."""
    text = (text or "").strip()
    if len(text) < 8:
        return _heuristic_classification(text)
    system = (
        "You are a thoughtful family biographer. Read the passage and return "
        "STRICT JSON (no markdown) with these keys:\n{\n" + _CLASSIFY_SPEC + "}\n\n"
        + _BUCKET_GUIDE
        + (f"\nSpeaker's birth year (if known): {birth_year}." if birth_year else "")
    )
    try:
        return _clean_classification(_chat_json(system, text, max_tokens=500))
    except Exception as e:
        logger.info("score_and_classify fell back to heuristic: %s", e)
        return _heuristic_classification(text)


# ── Polly's in-persona interjection (the Chatter button) ──────────────────

POLLY_PERSONA = (
    "You are Polly — a warm, curious African grey parrot who is the family's "
    "beloved companion and keeper of stories. You are NOT a generic chatbot. "
    "You speak like a cherished member of the family chiming into the "
    "conversation: warm, a little playful, genuinely interested, never "
    "intrusive, never corrective. You help people feel heard and help stories "
    "come out. You may use an occasional 🦜 but don't overdo it."
)


def polly_interjection(thread_text: str, member_names=None, birth_year=None,
                       theme=None) -> dict:
    """Polly reads a Chatter/Wall thread (the whole campfire — posts AND
    comments) and returns her 2 cents + follow-ups + the same classification
    used for capture. Never raises.

    theme: the Chatter group's name (e.g. "College Life", "Grandma's House") —
           Polly centers her reply and the narrative summary on it.

    Returns: {interjection, questions:[...], <classification keys...>}
    """
    thread_text = (thread_text or "").strip()
    names = ", ".join(member_names) if member_names else ""
    system = (
        POLLY_PERSONA + "\n\nRead the whole conversation below — it's a group of "
        "friends or family sharing memories around a theme, like a campfire. "
        "Take in every message, then return STRICT JSON (no markdown) with these keys:\n{\n"
        '  "interjection": "<1-3 warm sentences chiming into the conversation as '
        "if you are part of the group — react to what everyone said and gently "
        'invite more of the story. Address people by name when natural.>",\n'
        '  "questions": ["1-3 short, thoughtful follow-up questions that deepen '
        'connection — never redirect attention to yourself"],\n'
        + _CLASSIFY_SPEC + "}\n\n" + _BUCKET_GUIDE
        + (f"\nThis group's theme is: '{theme}'. Center your reply and the "
           f"narrative summary on that theme." if theme else "")
        + (f"\nPeople in this group: {names}." if names else "")
        + (f"\nSpeaker's birth year (if known): {birth_year}." if birth_year else "")
    )
    try:
        parsed = _chat_json(system, thread_text, max_tokens=800)
        result = _clean_classification(parsed)
        result["interjection"] = (str(parsed.get("interjection") or "")).strip()
        q = parsed.get("questions")
        result["questions"] = (
            [str(x).strip() for x in q if str(x).strip()][:3]
            if isinstance(q, list) else []
        )
        if not result["interjection"]:
            result["interjection"] = "Oh, I love hearing this. Tell me more? 🦜"
        return result
    except Exception as e:
        logger.info("polly_interjection fell back: %s", e)
        result = _heuristic_classification(thread_text)
        result["interjection"] = (
            "I love this — there's a real story here. Keep going, I'm listening. 🦜"
        )
        result["questions"] = [
            "What do you remember most about that?",
            "Who else was there?",
            "Is this a story your family still tells?",
        ]
        return result


def narrate_group(thread_text: str, theme=None, owner_name=None) -> dict:
    """Weave a whole Chatter group's conversation (posts + comments) into a
    warm narrative for the legacy book, told from the OWNER's point of view —
    so each person who saves it gets a story centered on their own life, with
    the friends woven in. The user reviews/edits and names it before saving.
    Returns {title, narrative}. Never raises.
    """
    thread_text = (thread_text or "").strip()
    who = (owner_name or "").strip()
    pov = (
        f"Write this as {who}'s OWN memory, told from {who}'s point of view — "
        f"center it on {who}'s life and experiences, and tell the fun stories about "
        f"the friends who were part of it and how everyone's lives intertwined with "
        f"{who}'s. "
        if who else
        "Write it from the owner's own point of view — centered on their life and the "
        "friends who were part of it, and how everyone's lives intertwined. "
    )
    system = (
        POLLY_PERSONA + "\n\nBelow is a whole conversation among a group of "
        "friends or family sharing memories"
        + (f", themed around '{theme}'" if theme else "")
        + ". " + pov
        + "Weave it into a warm, flowing narrative for a keepsake legacy book — tell "
        "it like a story that captures the people, the moments, the humor and the "
        "heart. Keep real names exactly as written. Return STRICT JSON (no markdown):\n{\n"
        '  "title": "<a short, warm title for this narrative'
        + (f' (something like \"{theme}\")' if theme else "") + '>",\n'
        '  "narrative": "<2-5 warm paragraphs, centered on '
        + (f"{who}" if who else "the owner") + ' with the friends woven in>"\n}'
    )
    try:
        parsed = _chat_json(system, thread_text, max_tokens=1200)
        title = (str(parsed.get("title") or theme or "Our Story")).strip()
        narrative = (str(parsed.get("narrative") or "")).strip()
        if not narrative:
            narrative = thread_text
        return {"title": title, "narrative": narrative}
    except Exception as e:
        logger.info("narrate_group fell back: %s", e)
        return {"title": theme or "Our Story", "narrative": thread_text}


# ── Capture: write the memory (the funnel's collection point) ─────────────

def _birth_year(conn, tenant_id):
    if not tenant_id:
        return None
    try:
        row = conn.execute(
            "SELECT birth_year FROM user_profiles WHERE tenant_id = ? LIMIT 1",
            (tenant_id,)
        ).fetchone()
        return row[0] if row and row[0] else None
    except Exception:
        return None


def already_captured(db, source: str, source_ref, tenant_id: int) -> bool:
    """True if this exact source item already produced a memory."""
    if source_ref is None:
        return False
    conn = db._get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM memories WHERE source = ? AND source_ref = ? "
            "AND tenant_id = ? LIMIT 1",
            (source, source_ref, tenant_id)
        ).fetchone()
        return row is not None
    finally:
        if not db._conn:
            conn.close()


def capture(db, tenant_id: int, text: str, source: str, source_ref=None,
            speaker: str = None, analysis: dict = None,
            photo_filename: str = None, is_quote: bool = False,
            include_in_book: int = 1, force: bool = False) -> int:
    """Funnel one item into stories + memories. Returns memory id, or 0 on skip.

    - source: 'chatter' | 'wall' | 'photo' | 'story' | 'question' | 'interview'
    - source_ref: id of the originating post/photo/wall item (dedupe key)
    - analysis: a pre-computed score_and_classify/polly_interjection dict
                (reused so we don't pay for a second GPT call)
    - force: bypass the (source, source_ref) dedupe guard. Used when one source
             item yields several memories (e.g. a photo narrative + its quotes);
             the caller dedupes once up front.
    """
    text = (text or "").strip()
    if not text and not photo_filename:
        return 0
    if not force and already_captured(db, source, source_ref, tenant_id):
        return 0

    conn = db._get_connection()
    try:
        birth_year = _birth_year(conn, tenant_id)
        if analysis is None:
            analysis = score_and_classify(text, birth_year=birth_year)

        # Raw archive row (keeps audio/photo + full provenance)
        attribution = f"[From {source.capitalize()}" + (
            f" — {speaker}]" if speaker else "]")
        transcript = f"{attribution}\n\n{text}" if text else attribution
        cur = conn.execute(
            "INSERT INTO stories (tenant_id, transcript, speaker_name, source, "
            "created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (tenant_id, transcript, speaker, source)
        )
        story_id = cur.lastrowid

        if photo_filename:
            conn.execute(
                "INSERT INTO photos (tenant_id, filename, caption, story_id, "
                "created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (tenant_id, photo_filename,
                 (analysis.get("summary") or f"From {source}")[:200], story_id)
            )

        cur = conn.execute(
            "INSERT INTO memories (story_id, speaker, bucket, life_phase, "
            "estimated_year, text_summary, text, people, locations, emotions, "
            "fingerprint, tenant_id, source, source_ref, include_in_book, "
            "is_quote, story_value) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                story_id, speaker, analysis["bucket"], analysis["life_phase"],
                analysis.get("estimated_year"), analysis.get("summary") or "",
                text, json.dumps(analysis.get("people") or []),
                json.dumps(analysis.get("locations") or []),
                json.dumps(analysis.get("emotions") or []),
                "", tenant_id, source, source_ref,
                1 if include_in_book else 0, 1 if is_quote else 0,
                analysis.get("story_value"),
            )
        )
        memory_id = cur.lastrowid
        conn.commit()
        logger.info("Captured memory %s from %s (value=%.2f, bucket=%s)",
                    memory_id, source, analysis.get("story_value") or 0,
                    analysis["bucket"])
        return memory_id
    finally:
        if not db._conn:
            conn.close()
