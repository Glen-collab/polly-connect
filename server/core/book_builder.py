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

        chapters = []
        chapter_num = 1

        for template in CHAPTER_TEMPLATES:
            key = (template["bucket"], template["life_phase"])
            group_memories = grouped.get(key, [])

            if not group_memories:
                continue

            # Split large groups into multiple chapters (max 10 per chapter)
            for i in range(0, len(group_memories), 10):
                chunk = group_memories[i:i + 10]
                if len(chunk) < 2:
                    continue

                title = template["title_template"]
                if i > 0:
                    title += f" (Part {i // 10 + 1})"

                chapters.append({
                    "chapter_number": chapter_num,
                    "title": title,
                    "bucket": template["bucket"],
                    "life_phase": template["life_phase"],
                    "memory_count": len(chunk),
                    "memory_ids": [m["id"] for m in chunk],
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
                                      speaker: str = None) -> Optional[str]:
        """
        Generate a narrative chapter draft from memories.
        Requires AI (OPENAI_API_KEY). Returns None if not available.
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

        # Build prompt for AI
        memory_texts = []
        for i, mem in enumerate(memories, 1):
            speaker_name = mem.get("speaker", "someone")
            text = mem.get("text", mem.get("text_summary", ""))
            emotions = ", ".join(mem.get("emotions", "").split(",")) if mem.get("emotions") else ""
            entry = f"Memory {i} ({speaker_name}): {text}"
            if emotions:
                entry += f" [emotions: {emotions}]"
            # Check if this memory came from a photo
            story_id = mem.get("story_id")
            if story_id:
                story = self.db.get_story_by_id(story_id)
                if story and story.get("photo_id"):
                    photo = self.db.get_photo_by_id(story["photo_id"])
                    if photo:
                        photo_note = f" [prompted by a photo"
                        if photo.get("caption"):
                            photo_note += f": {photo['caption']}"
                        if photo.get("date_taken"):
                            photo_note += f", {photo['date_taken']}"
                        photo_note += "]"
                        entry += photo_note
            memory_texts.append(entry)

        prompt = f"""You are writing a chapter of a family legacy book.
Chapter title: "{chapter['title']}"
Theme: {chapter['bucket'].replace('_', ' ')}
Life phase: {chapter['life_phase']}

Here are the memories to weave into this chapter:

{chr(10).join(memory_texts)}

Write a warm, narrative chapter (7-10 paragraphs) that:
- Weaves these memories into a cohesive story
- Preserves the speaker's voice and emotional tone
- Adds gentle transitions between memories
- Opens with a scene-setting paragraph
- Closes with a reflective paragraph
- Uses second person sparingly, mostly third person narrative
- Keeps a blue-collar, honest, heartfelt tone
- If a memory was prompted by a photo, reference it naturally (e.g. "In the photo, you can still see...")

Write the chapter now:"""

        try:
            import asyncio
            result = await asyncio.to_thread(
                self.followup_gen._call_openai,
                "Write this chapter", prompt, 1
            )
            if result:
                return result[0] if isinstance(result, list) else str(result)
        except Exception as e:
            logger.error(f"Chapter generation failed: {e}")

        return None

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
