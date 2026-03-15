"""
Book builder for Polly Connect.

Assembles verified memories into chapter outlines and narrative drafts.
Uses Jungian narrative buckets and life phases for chapter organization.

Hybrid: generates chapter outlines always (template), full narrative when
OPENAI_API_KEY is set.

Target: 20 chapters, 150-200 pages over ~12 months of memory collection.
"""

import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# Chapter templates — how to organize memories into chapters
CHAPTER_TEMPLATES = [
    {"bucket": "ordinary_world", "life_phase": "childhood",
     "title_template": "Where It All Started", "min_memories": 5},
    {"bucket": "ordinary_world", "life_phase": "childhood",
     "title_template": "The Kitchen Table", "min_memories": 5},
    {"bucket": "ordinary_world", "life_phase": "adolescence",
     "title_template": "Growing Up", "min_memories": 5},
    {"bucket": "call_to_adventure", "life_phase": "adolescence",
     "title_template": "When Things Changed", "min_memories": 5},
    {"bucket": "call_to_adventure", "life_phase": "young_adult",
     "title_template": "Stepping Out", "min_memories": 5},
    {"bucket": "crossing_threshold", "life_phase": "young_adult",
     "title_template": "The Decision", "min_memories": 5},
    {"bucket": "crossing_threshold", "life_phase": "young_adult",
     "title_template": "Love and Beginnings", "min_memories": 5},
    {"bucket": "trials_allies_enemies", "life_phase": "adult",
     "title_template": "The Hard Years", "min_memories": 5},
    {"bucket": "trials_allies_enemies", "life_phase": "adult",
     "title_template": "Who Stood By Me", "min_memories": 5},
    {"bucket": "trials_allies_enemies", "life_phase": "adult",
     "title_template": "Raising a Family", "min_memories": 5},
    {"bucket": "transformation", "life_phase": "adult",
     "title_template": "How I Changed", "min_memories": 5},
    {"bucket": "transformation", "life_phase": "midlife",
     "title_template": "Finding My Way", "min_memories": 5},
    {"bucket": "return_with_knowledge", "life_phase": "reflection",
     "title_template": "What I Know Now", "min_memories": 5},
    {"bucket": "return_with_knowledge", "life_phase": "reflection",
     "title_template": "For the Grandkids", "min_memories": 5},
]


class BookBuilder:
    """Assembles memories into chapter outlines and narrative drafts."""

    def __init__(self, db, followup_generator=None):
        self.db = db
        self.followup_gen = followup_generator
        self._ai_available = (followup_generator is not None
                              and followup_generator.available)

    def generate_chapter_outline(self, speaker: str = None,
                                  verified_only: bool = False,
                                  tenant_id: int = None) -> List[Dict]:
        """
        Generate a chapter outline from available memories.

        Returns list of chapter dicts with:
          chapter_number, title, bucket, life_phase, memory_count, memory_ids, status
        """
        memories = self.db.get_memories(
            speaker=speaker,
            verification_status="verified" if verified_only else None,
            limit=9999,
            tenant_id=tenant_id,
        )

        if not memories:
            return []

        # Group memories by bucket + life_phase
        grouped = {}
        for mem in memories:
            key = (mem.get("bucket", "ordinary_world"),
                   mem.get("life_phase", "unknown"))
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(mem)

        # Sort each group by estimated_year (chronological within bucket)
        for key in grouped:
            grouped[key].sort(
                key=lambda m: (m.get("estimated_year") or 9999, m.get("id", 0))
            )

        chapters = []
        chapter_num = 1
        # Track how many memories have been assigned per bucket/life_phase
        # so the second template only fires when there are surplus memories (>10)
        assigned = {}

        for template in CHAPTER_TEMPLATES:
            key = (template["bucket"], template["life_phase"])
            group_memories = grouped.get(key, [])

            if not group_memories:
                continue

            # Skip memories already assigned to a previous template for this key
            offset = assigned.get(key, 0)
            remaining = group_memories[offset:]

            # Only create a second chapter for the same bucket/phase if
            # there are enough surplus memories to justify it
            if offset > 0 and len(remaining) < 5:
                continue

            if len(remaining) < 2:
                continue

            # Take up to 10 memories for this chapter
            chunk = remaining[:10]
            assigned[key] = offset + len(chunk)

            title = template["title_template"]

            # Calculate year range for this chunk
            years = [m.get("estimated_year") for m in chunk
                     if m.get("estimated_year")]
            year_range = None
            if years:
                year_range = (min(years), max(years))

            chapters.append({
                "chapter_number": chapter_num,
                "title": title,
                "bucket": template["bucket"],
                "life_phase": template["life_phase"],
                "memory_count": len(chunk),
                "memory_ids": [m["id"] for m in chunk],
                "year_range": year_range,
                "status": "ready" if len(chunk) >= template["min_memories"] else "needs_more",
            })
            chapter_num += 1

        return chapters

    def get_book_progress(self, speaker: str = None, tenant_id: int = None) -> Dict:
        """Get overall book-building progress stats."""
        memories = self.db.get_memories(speaker=speaker, limit=9999, tenant_id=tenant_id)
        verified = [m for m in memories if m.get("verification_status") == "verified"]
        outline = self.generate_chapter_outline(speaker, tenant_id=tenant_id)
        ready_chapters = [c for c in outline if c["status"] == "ready"]

        return {
            "total_memories": len(memories),
            "verified_memories": len(verified),
            "total_chapters_outlined": len(outline),
            "chapters_ready": len(ready_chapters),
            "estimated_pages": len(verified) * 2,  # ~2 pages per memory
            "target_pages": 175,
            "percent_complete": min(100, int((len(verified) / 90) * 100)) if verified else 0,
        }

    async def generate_chapter_draft(self, chapter: Dict,
                                      speaker: str = None,
                                      tenant_id: int = None,
                                      previous_summaries: List[str] = None) -> Optional[str]:
        """
        Generate a narrative chapter draft from memories.
        Requires AI (OPENAI_API_KEY). Returns None if not available.

        previous_summaries: list of 2-sentence summaries from earlier chapters,
        used to maintain narrative continuity across the book.
        """
        if not self._ai_available:
            return None

        memory_ids = chapter.get("memory_ids", [])
        if not memory_ids:
            return None

        # Fetch full memory texts
        memories = []
        for mid in memory_ids:
            mem = self.db.get_memory_by_id(mid)
            if mem:
                memories.append(mem)

        if not memories:
            return None

        # Sort memories chronologically
        memories.sort(
            key=lambda m: (m.get("estimated_year") or 9999, m.get("id", 0))
        )

        # Build timeline context from estimated_year and birth_year data
        timeline_notes = []
        owner_birth_year = None

        # Look up owner birth year
        if tenant_id:
            conn = self.db._get_connection()
            try:
                owner = conn.execute(
                    "SELECT name, birth_year FROM user_profiles WHERE tenant_id = ? LIMIT 1",
                    (tenant_id,)
                ).fetchone()
                if owner and owner[1]:
                    owner_birth_year = owner[1]
                    owner_name = owner[0] or speaker or "the owner"
                    timeline_notes.append(f"- {owner_name} was born in {owner_birth_year}")
            finally:
                pass

        for mem in memories:
            est_year = mem.get("estimated_year")
            o_age = mem.get("owner_age")
            confidence = mem.get("year_confidence", "none")
            speaker_name = mem.get("speaker", "someone")
            summary = (mem.get("text_summary") or mem.get("text", ""))[:60]
            if est_year:
                note = f"- \"{summary}...\" — ~{est_year}"
                if o_age is not None:
                    note += f" ({owner_name if owner_birth_year else 'owner'} was {o_age})"
                if confidence == "low":
                    note += " [approximate]"
                timeline_notes.append(note)

        # Collect available photos for this chapter (with timeline data)
        available_photos = []
        photo_lookup = {}  # story_id -> photo info
        for mem in memories:
            story_id = mem.get("story_id")
            if not story_id:
                continue
            story = self.db.get_story_by_id(story_id)
            if not story or not story.get("photo_id"):
                continue
            if not story.get("photo_in_book", 1):
                continue
            photo = self.db.get_photo_by_id(story["photo_id"])
            if not photo:
                continue
            # Build date context from photo, memory, and family data
            photo_year = None
            if photo.get("date_taken"):
                import re
                yr_match = re.search(r'(19\d{2}|20\d{2})', str(photo["date_taken"]))
                if yr_match:
                    photo_year = int(yr_match.group(1))
            if not photo_year:
                photo_year = mem.get("estimated_year")

            # Parse people from photo tags
            people_in_photo = []
            if photo.get("tags"):
                import json as _json
                try:
                    tags = _json.loads(photo["tags"]) if isinstance(photo["tags"], str) else photo["tags"]
                    people_in_photo = [t for t in tags if isinstance(t, str)]
                except (ValueError, TypeError):
                    pass

            info = {
                "story_id": story_id,
                "caption": photo.get("caption", ""),
                "date_taken": photo.get("date_taken", ""),
                "photo_year": photo_year,
                "people": people_in_photo,
            }
            available_photos.append(info)
            photo_lookup[story_id] = info

        # Build memory entries for prompt
        memory_texts = []
        for i, mem in enumerate(memories, 1):
            speaker_name = mem.get("speaker", "someone")
            text = mem.get("text", mem.get("text_summary", ""))
            raw_emotions = mem.get("emotions", "")
            if isinstance(raw_emotions, list):
                emotions = ", ".join(raw_emotions)
            elif raw_emotions:
                emotions = ", ".join(raw_emotions.split(","))
            else:
                emotions = ""
            est_year = mem.get("estimated_year")
            o_age = mem.get("owner_age")

            entry = f"Memory {i} ({speaker_name}"
            if est_year:
                entry += f", ~{est_year}"
            if o_age is not None:
                entry += f", owner age {o_age}"
            entry += f"): {text}"

            if emotions:
                entry += f" [emotions: {emotions}]"

            # Note if this memory has a photo available
            story_id = mem.get("story_id")
            if story_id and story_id in photo_lookup:
                p = photo_lookup[story_id]
                photo_note = f" [HAS PHOTO story_id={story_id}"
                if p["caption"]:
                    photo_note += f", caption: {p['caption']}"
                if p["date_taken"]:
                    photo_note += f", taken: {p['date_taken']}"
                if p["people"]:
                    photo_note += f", people: {', '.join(p['people'])}"
                photo_note += "]"
                entry += photo_note
            memory_texts.append(entry)

        # Build continuity block from previous chapters
        continuity_block = ""
        if previous_summaries:
            continuity_block = "\n\nPrevious chapters (for continuity — do NOT repeat these stories, build on them):\n"
            for j, summ in enumerate(previous_summaries, 1):
                continuity_block += f"Ch {j}: {summ}\n"
            continuity_block += "\n"

        timeline_block = ""
        if timeline_notes:
            timeline_block = f"""

Timeline context:
{chr(10).join(timeline_notes)}

"""

        # Build photo placement instructions
        photo_block = ""
        if available_photos:
            photo_lines = []
            for p in available_photos:
                line = f"  - [PHOTO:{p['story_id']}]"
                if p["caption"]:
                    line += f" — {p['caption']}"
                if p["photo_year"]:
                    line += f" (~{p['photo_year']})"
                if p["people"]:
                    line += f" — people: {', '.join(p['people'])}"
                photo_lines.append(line)
            photo_block = f"""

Available photos for this chapter:
{chr(10).join(photo_lines)}

PHOTO PLACEMENT RULES:
- Place each photo marker on its OWN line, right AFTER the paragraph that discusses that time period, person, or event
- Format: [PHOTO:story_id] on a line by itself between paragraphs
- Match photos to content by year, people mentioned, and caption context
- Use family birth years to calculate when events happened (e.g. if a child was born in 2018 and the story mentions their first steps, that photo belongs around 2019)
- Every available photo MUST be placed exactly once
- Reference the photo naturally in the paragraph above it (e.g. "In the photo from that day..." or "captured in a snapshot from that summer...")
"""

        # Build family context for date calculation
        family_block = ""
        if tenant_id:
            conn = self.db._get_connection()
            try:
                fam = conn.execute(
                    "SELECT name, relationship, birth_year, deceased_year FROM family_members WHERE tenant_id = ? AND birth_year IS NOT NULL",
                    (tenant_id,)
                ).fetchall()
                if fam:
                    fam_lines = [f"  - {f[0]} ({f[1]}): born {f[2]}" + (f", passed {f[3]}" if f[3] else "") for f in fam]
                    family_block = f"""

Family timeline (use these to calculate when events happened):
{chr(10).join(fam_lines)}
"""
            finally:
                pass

        prompt = f"""You are writing a chapter of a family legacy book.
Chapter {chapter.get('chapter_number', '?')}: "{chapter['title']}"
Theme: {chapter['bucket'].replace('_', ' ')}
Life phase: {chapter['life_phase']}
{timeline_block}{family_block}{continuity_block}
Here are the memories to weave into this chapter (sorted chronologically):

{chr(10).join(memory_texts)}
{photo_block}
Write a warm, narrative chapter (7-10 paragraphs) that:
- Weaves these memories into a cohesive story in chronological order
- Preserves the speaker's voice and emotional tone
- Adds gentle transitions between memories
- Opens with a scene-setting paragraph grounded in time and place
- Closes with a reflective paragraph
- Uses second person sparingly, mostly third person narrative
- Keeps a blue-collar, honest, heartfelt tone
- When timeline dates are available, ground the narrative in specific years or decades (e.g. "It was the summer of '58..." instead of "Back then...")
- When owner age is given, use it to anchor the perspective (e.g. "At nine years old, the world still felt enormous...")
- Use family birth years to anchor events (e.g. if Brooklyn was born in 2018 and the story mentions her gymnastics, that's ~2024-2026)
- Do NOT repeat stories or themes already covered in previous chapters
- If photos are available, place [PHOTO:story_id] markers on their own line right after the relevant paragraph

Write the chapter now:"""

        try:
            import asyncio
            result = await asyncio.to_thread(self._call_chapter_openai, prompt)
            return result
        except Exception as e:
            logger.error(f"Chapter generation failed: {e}")

        return None

    async def generate_chapter_summary(self, content: str) -> Optional[str]:
        """Generate a 2-sentence summary of a chapter for continuity."""
        if not self._ai_available or not content:
            return None

        prompt = f"""Summarize this book chapter in exactly 2 sentences. Focus on the key events, people, and time period covered. Be specific.

{content[:3000]}

Two-sentence summary:"""

        try:
            import asyncio
            result = await asyncio.to_thread(self._call_chapter_openai, prompt)
            return result
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            return None

    def _call_chapter_openai(self, prompt: str) -> Optional[str]:
        """Direct OpenAI call for chapter generation (not the follow-up generator)."""
        response = self.followup_gen._client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.7,
        )
        text = response.choices[0].message.content.strip()
        return text if text else None

    def save_chapter_draft(self, chapter_number: int, title: str,
                           bucket: str, life_phase: str,
                           memory_ids: List[int], content: str) -> int:
        """Save a chapter draft to the database."""
        return self.db.save_chapter_draft(
            chapter_number=chapter_number,
            title=title,
            bucket=bucket,
            life_phase=life_phase,
            memory_ids=json.dumps(memory_ids),
            content=content,
        )
