"""
Book builder for Polly Connect.

Assembles verified memories into chapter outlines and narrative drafts.
Uses Jungian narrative buckets and life phases for chapter organization.

Hybrid: generates chapter outlines always (template), full narrative when
OPENAI_API_KEY is set.

Target: 20 chapters, 150-200 pages over ~12 months of memory collection.
"""

import json
import os
import re
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


# The 6 life-arc buckets. The book is "ready" when each holds enough memories.
LIFE_BUCKETS = [
    "ordinary_world", "call_to_adventure", "crossing_threshold",
    "trials_allies_enemies", "transformation", "return_with_knowledge",
]
MIN_PER_BUCKET = 5  # memories per bucket before a life stage counts as "full"

CHAPTER_CAP = 10  # memories per chapter before a new one starts

# Reading order of the book: life stage first, then arc within it
PHASE_ORDER = ["childhood", "adolescence", "young_adult", "adult", "midlife",
               "elder", "reflection", "unknown"]


def _stable_order(ch: Dict) -> tuple:
    """Reading order: life stage, then arc, then the chapter's earliest story.
    Uses nothing that changes when a chapter is written (not titles, not
    draft status), so the outline is the same before and after writing."""
    p = ch["life_phase"] if ch["life_phase"] in PHASE_ORDER else "unknown"
    b = LIFE_BUCKETS.index(ch["bucket"]) if ch["bucket"] in LIFE_BUCKETS else len(LIFE_BUCKETS)
    catch_all = ch.get("catch_all", False)
    return (catch_all, PHASE_ORDER.index(p), b, min(ch["memory_ids"], default=0))


def strip_heading(text: str) -> str:
    """Drop a heading line the model sometimes writes itself
    ('**Chapter 9: "Ordinary World (more)"**') — the PDF prints its own
    heading, and this one would carry a stale placeholder title."""
    lines = (text or "").lstrip().split("\n")
    if lines and re.match(r'^[#*\s]*chapter\b.{0,120}$', lines[0].strip(), re.IGNORECASE):
        return "\n".join(lines[1:]).lstrip()
    return text


# Life stage by age at the time (matches the classifier's guide)
def phase_for_age(age: int) -> str:
    if age <= 12:
        return "childhood"
    if age <= 18:
        return "adolescence"
    if age <= 30:
        return "young_adult"
    if age <= 50:
        return "adult"
    if age <= 70:
        return "midlife"
    return "elder"


PHASE_LABELS_PLAIN = {"childhood": "childhood", "adolescence": "teenage years",
                      "young_adult": "young adult years", "adult": "adult years",
                      "midlife": "middle years", "elder": "later years",
                      "reflection": "reflections looking back"}


def _placement(mem: Dict) -> str:
    return f"{mem.get('bucket') or 'ordinary_world'}/{mem.get('life_phase') or 'unknown'}"


def _draft_ids(draft: Dict, field: str = "memory_ids") -> List[int]:
    raw = draft.get(field) or "[]"
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = []
    return [int(x) for x in raw]


class BookBuilder:
    """Assembles memories into chapter outlines and narrative drafts."""

    def __init__(self, db, followup_generator=None):
        self.db = db
        self.followup_gen = followup_generator
        self._ai_available = (followup_generator is not None
                              and followup_generator.available)

    def book_readiness(self, speaker: str = None, tenant_id: int = None) -> Dict:
        """Is the book 'full' enough to generate? Ready when every life-stage
        bucket has at least MIN_PER_BUCKET in-book memories."""
        mems = self.db.get_memories(speaker=speaker, limit=9999,
                                    tenant_id=tenant_id, in_book_only=True)
        counts = {b: 0 for b in LIFE_BUCKETS}
        for m in mems:
            b = m.get("bucket") or "ordinary_world"
            if b in counts:
                counts[b] += 1
        ready_buckets = [b for b, c in counts.items() if c >= MIN_PER_BUCKET]
        return {
            "ready": len(ready_buckets) == len(LIFE_BUCKETS),
            "counts": counts,
            "ready_count": len(ready_buckets),
            "total_buckets": len(LIFE_BUCKETS),
            "min_per_bucket": MIN_PER_BUCKET,
        }

    @staticmethod
    def _age_to_bucket(age: int, current_age: int) -> tuple:
        """Assign Jungian arc bucket relative to current age, not fixed cutoffs.

        The arc scales to wherever you are in life right now:
        - Childhood is always 0-12 (universal)
        - Adolescence is always 13-18 (universal)
        - Everything after 18 is divided proportionally up to current_age
        - The last ~15% of your life so far = return_with_knowledge (wisdom/reflection)
        - The chunk before that = transformation (how you changed)
        - The rest of adulthood splits between crossing_threshold and trials

        A 47-year-old teaching their kids → "return with knowledge"
        A 47-year-old at age 35 → "trials_allies_enemies"
        An 80-year-old at age 47 → "trials_allies_enemies"
        """
        if age <= 12:
            return ("ordinary_world", "childhood")
        if age <= 18:
            return ("call_to_adventure", "adolescence")

        # Adult years: 19 to current_age
        adult_span = max(current_age - 18, 1)
        adult_age = age - 18  # how far into adulthood

        # Proportional splits of adult life
        # 0-40%: crossing_threshold (young adult, building life)
        # 40-70%: trials_allies_enemies (middle years, hard work)
        # 70-85%: transformation (how you changed)
        # 85-100%: return_with_knowledge (wisdom, teaching, now)
        pct = adult_age / adult_span

        if pct <= 0.40:
            return ("crossing_threshold", "young_adult")
        elif pct <= 0.70:
            return ("trials_allies_enemies", "adult")
        elif pct <= 0.85:
            return ("transformation", "midlife")
        else:
            return ("return_with_knowledge", "reflection")

    def _guess_wedding_year(self, tenant_id: int) -> Optional[int]:
        """Try to find wedding year from family data or photos."""
        conn = self.db._get_connection()
        # Check photos with "wedding" in caption
        photos = conn.execute(
            "SELECT date_taken FROM photos WHERE tenant_id = ? AND LOWER(caption) LIKE '%wedding%'",
            (tenant_id,)
        ).fetchall()
        for p in photos:
            if p[0]:
                import re
                m = re.search(r'(19\d{2}|20\d{2})', str(p[0]))
                if m:
                    return int(m.group(1))
        return None

    def _guess_birth_year_from_text(self, text: str, tenant_id: int) -> Optional[int]:
        """Try to figure out which child's birth is mentioned and return their birth year."""
        conn = self.db._get_connection()
        members = conn.execute(
            "SELECT name, birth_year FROM family_members WHERE tenant_id = ? AND birth_year IS NOT NULL AND relationship IN ('daughter', 'son')",
            (tenant_id,)
        ).fetchall()
        for name, by in members:
            if name.lower() in text:
                return by
        return None

    def generate_chapter_outline(self, speaker: str = None,
                                  verified_only: bool = False,
                                  tenant_id: int = None) -> List[Dict]:
        """
        Generate a chapter outline from available memories.

        Chapters hold the stories the owner has VERIFIED (the ✔ on the story —
        "the words are right, tell this one"). Unverified stories are not
        dropped: the PDF keeps them in an appendix (QR + title, not the
        unchecked transcript). Only the 📖 toggle leaves a story out entirely.
        Every eligible memory lands in exactly one chapter.

        The old filter read memories.verification_status, which the web ✔
        never set, so verified stories silently never reached the book.

        Read-only: building the outline never writes to the database.

        Returns list of chapter dicts with:
          chapter_number, title, bucket, life_phase, memory_count, memory_ids, status
        """
        memories = self.db.get_memories(
            speaker=speaker,
            limit=9999,
            tenant_id=tenant_id,
            in_book_only=True,
        )
        if tenant_id:
            unreviewed = self.unreviewed_story_ids(tenant_id)
            memories = [m for m in memories if m.get("story_id") not in unreviewed]

        if not memories:
            return []

        # Auto-date undated memories from linked story/photo data
        owner_birth_year = None
        if tenant_id:
            conn = self.db._get_connection()
            owner = conn.execute(
                "SELECT birth_year FROM user_profiles WHERE tenant_id = ? LIMIT 1",
                (tenant_id,)
            ).fetchone()
            if owner and owner[0]:
                owner_birth_year = owner[0]

        for mem in memories:
            if mem.get("estimated_year"):
                continue
            story_id = mem.get("story_id")
            if not story_id:
                continue
            story = self.db.get_story_by_id(story_id, tenant_id=tenant_id)
            if not story:
                continue
            # Try to extract year from photo date_taken
            est_year = None
            if story.get("photo_id"):
                photo = self.db.get_photo_by_id(story["photo_id"], tenant_id=tenant_id)
                if photo and photo.get("date_taken"):
                    import re
                    yr_match = re.search(r'(19\d{2}|20\d{2})', str(photo["date_taken"]))
                    if yr_match:
                        est_year = int(yr_match.group(1))
            # Try transcript text
            if not est_year:
                import re
                text = story.get("corrected_transcript") or story.get("transcript") or ""
                yr_match = re.search(r'(19\d{2}|20\d{2})', text)
                if yr_match:
                    est_year = int(yr_match.group(1))
            # Try keyword clues
            if not est_year:
                text = (story.get("corrected_transcript") or story.get("transcript") or "").lower()
                if "wedding" in text:
                    # Look up spouse marriage date from family_members
                    est_year = self._guess_wedding_year(tenant_id)
                elif "birth of" in text or "newborn" in text or "baby" in text:
                    est_year = self._guess_birth_year_from_text(text, tenant_id)

            if est_year:
                # Guessed year is used for ordering only. It must NOT move the
                # memory to another bucket or be saved: any year in the text
                # matches ("...and here we are in 2026"), which used to shove
                # childhood stories into the wisdom chapter on every page view.
                mem["estimated_year"] = est_year
                if owner_birth_year:
                    mem["owner_age"] = est_year - owner_birth_year

        # Group memories by bucket + life_phase
        grouped = {}
        for mem in memories:
            key = (mem.get("bucket") or "ordinary_world",
                   mem.get("life_phase") or "unknown")
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(mem)

        # Sort each group by estimated_year (chronological within bucket)
        for key in grouped:
            grouped[key].sort(
                key=lambda m: (m.get("estimated_year") or 9999, m.get("id", 0))
            )

        # Sticky chapters: a memory a chapter's draft already tells stays in
        # that chapter, so adding stories over the years never reshuffles
        # chapters that are written. New memories join a written chapter of
        # the same arc while it has room (it goes stale and is refreshed);
        # overflow starts new chapters below.
        chapters = []
        chapter_num = 1
        by_id = {m["id"]: m for m in memories}
        claimed = set()
        if tenant_id:
            drafts_now = self.db.get_chapter_drafts(tenant_id=tenant_id)
            draft_ids_now = {d["id"] for d in drafts_now}
            # "Move to this chapter": a pinned story belongs to that written
            # chapter no matter how it is sorted
            pinned = {m["id"]: m["pinned_draft_id"] for m in memories
                      if m.get("pinned_draft_id") in draft_ids_now}
            for d in drafts_now:
                # A story stays anchored unless its own placement changed
                # since the chapter was written (re-sorted, or moved by the
                # owner) — then it goes where it now belongs and both
                # chapters refresh.
                try:
                    placed_as = json.loads(d.get("placements") or "{}")
                except (ValueError, TypeError):
                    placed_as = {}
                ids = [i for i in _draft_ids(d) if i in by_id and i not in claimed
                       and pinned.get(i, d["id"]) == d["id"]
                       and (i in pinned or placed_as.get(str(i), _placement(by_id[i]))
                            == _placement(by_id[i]))]
                ids += [i for i, pd in pinned.items() if pd == d["id"] and i not in ids and i not in claimed]
                if not ids:
                    continue
                claimed.update(ids)
                first = by_id[ids[0]]
                chapters.append({
                    "chapter_number": chapter_num,
                    "title": d.get("title") or "Chapter",
                    "bucket": d.get("bucket") or first.get("bucket") or "ordinary_world",
                    "life_phase": d.get("life_phase") or first.get("life_phase") or "unknown",
                    "memory_ids": ids,
                    "draft_id": d["id"],
                })
                chapter_num += 1
            for key in grouped:
                grouped[key] = [m for m in grouped[key] if m["id"] not in claimed]
            for ch in chapters:
                key = (ch["bucket"], ch["life_phase"])
                room = CHAPTER_CAP - len(ch["memory_ids"])
                if room > 0 and grouped.get(key):
                    ch["memory_ids"] += [m["id"] for m in grouped[key][:room]]
                    grouped[key] = grouped[key][room:]
        used_titles = {ch["title"] for ch in chapters}
        # Track how many memories have been assigned per bucket/life_phase
        # so the second template only fires when there are surplus memories (>10)
        assigned = {}

        for template in CHAPTER_TEMPLATES:
            key = (template["bucket"], template["life_phase"])
            group_memories = grouped.get(key, [])

            if not group_memories or template["title_template"] in used_titles:
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

        # Richness: spill ALL leftover memories into extra chapters so the whole
        # library is used (fuller library -> bigger, richer book). Covers both
        # surplus beyond a template's chunk AND memories whose bucket/phase has
        # no matching template at all (which would otherwise be dropped).
        for key, group_memories in grouped.items():
            offset = assigned.get(key, 0)
            remaining = group_memories[offset:]
            if not remaining:
                continue
            bucket, life_phase = key
            base_title = next(
                (t["title_template"] for t in CHAPTER_TEMPLATES
                 if (t["bucket"], t["life_phase"]) == key),
                bucket.replace("_", " ").title())
            for start in range(0, len(remaining), 10):
                chunk = remaining[start:start + 10]
                if len(chunk) < 2:
                    continue
                years = [m.get("estimated_year") for m in chunk if m.get("estimated_year")]
                chapters.append({
                    "chapter_number": chapter_num,
                    "title": f"{base_title} (more)",
                    "bucket": bucket,
                    "life_phase": life_phase,
                    "memory_count": len(chunk),
                    "memory_ids": [m["id"] for m in chunk],
                    "year_range": (min(years), max(years)) if years else None,
                    "status": "ready" if len(chunk) >= 5 else "needs_more",
                })
                chapter_num += 1
            assigned[key] = len(group_memories)

        # Stragglers: a lone memory in its bucket/phase (or the 1 left over
        # after chunks of 10) is too small for its own chapter. Home it in the
        # closest chapter — same bucket+phase, then same phase, then same
        # bucket — or a final catch-all chapter. It is never dropped.
        placed = {mid for ch in chapters for mid in ch["memory_ids"]}
        leftovers = [m for m in memories if m["id"] not in placed]
        catch_all = None
        for mem in leftovers:
            b = mem.get("bucket") or "ordinary_world"
            p = mem.get("life_phase") or "unknown"
            # A little overflow is fine; past that a straggler opens a new
            # chapter, so years of additions can't grow one chapter forever.
            # Candidates in a fixed order that does not depend on which
            # chapters are written yet — otherwise writing one chapter moves a
            # straggler and makes another chapter stale.
            roomy = sorted((c for c in chapters if len(c["memory_ids"]) < CHAPTER_CAP + 3),
                           key=_stable_order)
            home = (next((c for c in roomy if (c["bucket"], c["life_phase"]) == (b, p)), None)
                    or next((c for c in roomy if c["life_phase"] == p and p != "unknown"), None)
                    or next((c for c in roomy if c["bucket"] == b), None))
            if home is None and any((c["bucket"], c["life_phase"]) == (b, p) for c in chapters):
                # Its arc's chapters are all full: continue that arc
                base = next(c["title"] for c in chapters if (c["bucket"], c["life_phase"]) == (b, p))
                home = {"chapter_number": chapter_num,
                        "title": base if base.endswith("(more)") else f"{base} (more)",
                        "bucket": b, "life_phase": p, "memory_ids": []}
                chapters.append(home)
                chapter_num += 1
            if home is None:
                if catch_all is None:
                    catch_all = {
                        "chapter_number": chapter_num,
                        "catch_all": True,
                        "title": "More Memories",
                        "bucket": b,
                        "life_phase": p,
                        "memory_count": 0,
                        "memory_ids": [],
                        "year_range": None,
                        "status": "needs_more",
                    }
                    chapters.append(catch_all)
                    chapter_num += 1
                home = catch_all
            home["memory_ids"].append(mem["id"])
            home["memory_count"] = len(home["memory_ids"])

        # Reading order: life stage, then arc, then written chapters first.
        # Numbers are display positions only — drafts attach by draft_id.
        chapters.sort(key=_stable_order)
        for n, ch in enumerate(chapters, 1):
            ch["chapter_number"] = n
            ch["memory_count"] = len(ch["memory_ids"])
            years = [by_id[m].get("estimated_year") for m in ch["memory_ids"]
                     if by_id[m].get("estimated_year")]
            ch["year_range"] = (min(years), max(years)) if years else None
            ch.setdefault("status", "ready" if ch["memory_count"] >= 5 else "needs_more")

        return chapters

    def unreviewed_story_ids(self, tenant_id: int) -> set:
        """Stories the owner hasn't ✔ verified — they go to the appendix."""
        conn = self.db._get_connection()
        try:
            return {r[0] for r in conn.execute(
                "SELECT id FROM stories WHERE tenant_id = ? AND COALESCE(verified, 0) = 0",
                (tenant_id,)).fetchall()}
        finally:
            if not self.db._conn:
                conn.close()

    def appendix_stories(self, tenant_id: int) -> List[Dict]:
        """Unverified stories that still belong in the book (not 📖'd out),
        oldest first. Wordless recordings are left to Voice Recordings."""
        conn = self.db._get_connection()
        try:
            import sqlite3
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT s.* FROM stories s
                WHERE s.tenant_id = ? AND COALESCE(s.verified, 0) = 0
                  AND NOT EXISTS (SELECT 1 FROM memories m WHERE m.story_id = s.id
                                  AND COALESCE(m.include_in_book, 1) = 0)
                ORDER BY s.created_at, s.id
            """, (tenant_id,)).fetchall()
        finally:
            if not self.db._conn:
                conn.close()
        out = []
        for r in rows:
            s = dict(r)
            text = ((s.get("corrected_transcript") or "").strip()
                    or (s.get("transcript") or "").strip())
            if not text or text.startswith("(no transcription"):
                continue
            out.append(s)
        return out

    def book_coverage(self, tenant_id: int) -> Dict:
        """Where every story lands in the book — or exactly why it doesn't.

        Mirrors the PDF: outline, drafts matched by content, uncovered
        memories printed word-for-word. Returns
          {"stories": [{story_id, preview, created_at, source, state, chapter,
                        mode, reason, memory_id}], "in_book": n, "total": n}
        state: "in_book" | "excluded" | "no_memory"
        """
        chapters = self.generate_chapter_outline(tenant_id=tenant_id)
        self.match_drafts(chapters, self.db.get_chapter_drafts(tenant_id=tenant_id))

        where = {}  # memory_id -> (chapter title, mode)
        for ch in chapters:
            if ch["draft"]:
                d = ch["draft"]
                try:
                    told = set(json.loads(d.get("memory_ids") or "[]")) - \
                        set(json.loads(d.get("missing_memory_ids") or "[]"))
                except (ValueError, TypeError):
                    told = set()
                for mid in told:
                    where.setdefault(mid, (ch["title"], "told in the AI chapter"))
        for ch in chapters:
            for mid in ch["uncovered_ids"]:
                where.setdefault(mid, (ch["title"], "printed word-for-word"))

        conn = self.db._get_connection()
        try:
            rows = conn.execute("""
                SELECT s.id, s.created_at, s.source,
                       COALESCE(NULLIF(TRIM(s.corrected_transcript), ''), s.transcript, '') AS text,
                       m.id AS mid, COALESCE(m.include_in_book, 1) AS inb,
                       (COALESCE(s.audio_s3_key, '') != '' AND COALESCE(s.qr_in_book, 1) = 1) AS has_qr,
                       s.question_text
                FROM stories s
                LEFT JOIN memories m ON m.story_id = s.id AND m.tenant_id = s.tenant_id
                WHERE s.tenant_id = ?
                ORDER BY s.created_at DESC, s.id DESC
            """, (tenant_id,)).fetchall()
        finally:
            if not self.db._conn:
                conn.close()

        appendix = {s["id"] for s in self.appendix_stories(tenant_id)}
        out, seen = [], set()
        for sid, created, source, text, mid, inb, has_qr, title in rows:
            if sid in seen:        # a story with >1 memory: first one decides
                continue
            seen.add(sid)
            text = (text or "").strip()
            no_words = not text or text.startswith("(no transcription")
            entry = {"story_id": sid, "created_at": created, "source": source,
                     "preview": (title or "").strip() if no_words else text[:140],
                     "memory_id": mid, "has_qr": bool(has_qr),
                     "chapter": None, "mode": None, "reason": None}
            if mid is not None and not inb:
                entry["state"] = "excluded"
                entry["reason"] = "You took this out of the book (📖)."
            elif sid in appendix:
                # Not ✔ verified: kept, but in the appendix — the voice (QR)
                # and title, not the unchecked transcript.
                entry["state"] = "in_book"
                entry["chapter"] = "Appendix (not verified yet)"
                entry["mode"] = ("QR code + title — verify it to move it into a chapter"
                                 if has_qr else "printed as typed — verify it to move it into a chapter")
            elif mid is None and has_qr and (no_words or len(text) < 10):
                # Audio-only moments (kids playing, Christmas chaos): the QR
                # code IS the story — it prints in the Voice Recordings section.
                entry["state"] = "in_book"
                entry["chapter"] = "Voice Recordings (end of book)"
                entry["mode"] = "QR code only — scan to hear it"
            elif mid is None:
                entry["state"] = "no_memory"
                if no_words:
                    entry["reason"] = "No words and no recording to link — type the story on its edit page."
                elif len(text) < 10:
                    entry["reason"] = "Too short to place in a chapter."
                elif has_qr:
                    entry["reason"] = ("Never sorted into a chapter. Its QR code prints in "
                                       "Voice Recordings, but the words aren't in the book yet.")
                else:
                    entry["reason"] = "Never sorted into a chapter."
            elif mid in where:
                entry["state"] = "in_book"
                entry["chapter"], entry["mode"] = where[mid]
                if has_qr:
                    entry["mode"] += " + QR code"
            else:
                # Should be impossible — every in-book memory is placed.
                entry["state"] = "no_memory"
                entry["reason"] = "Not placed — please report this."
            out.append(entry)

        return {"stories": out,
                "appendix": sum(1 for e in out if (e["chapter"] or "").startswith("Appendix")),
                "in_book": sum(1 for e in out if e["state"] == "in_book"),
                "total": len(out)}

    @staticmethod
    def match_drafts(chapters: List[Dict], drafts: List[Dict]) -> None:
        """Attach each chapter's draft — the one it is anchored to.

        The outline anchors every written chapter to its draft (draft_id), so
        there is no guessing by number or overlap. Sets on each chapter:
          draft            — the draft dict, or None
          draft_stale      — its memories changed since it was written
                             (stories added, or taken out / unverified)
          uncovered_ids    — chapter memories the prose does not tell (added
                             since, or the AI verifiably skipped) — these
                             print word-for-word after the chapter
        """
        by_id = {d["id"]: d for d in drafts}
        for ch in chapters:
            d = by_id.get(ch.get("draft_id"))
            ch["draft"] = d
            if not d:
                ch["draft_stale"] = False
                ch["uncovered_ids"] = list(ch.get("memory_ids", []))
                continue
            told = set(_draft_ids(d)) - set(_draft_ids(d, "missing_memory_ids"))
            ch["draft_stale"] = set(_draft_ids(d)) != set(ch.get("memory_ids", []))
            ch["uncovered_ids"] = [m for m in ch.get("memory_ids", []) if m not in told]

    def get_book_progress(self, speaker: str = None, tenant_id: int = None) -> Dict:
        """Book stats for the Legacy Book page and hubs.

        chapters_ready = chapters written and current (a stale one is about
        to be refreshed); percent_complete = share of chapters written;
        estimated_pages is worked out from what will actually print —
        calibrated on a real 73-page export: 6 pages front/back, half a page
        per chapter opening, 300 words a page, 0.6 per photo, 0.2 per QR.
        """
        memories = self.db.get_memories(speaker=speaker, limit=9999, tenant_id=tenant_id,
                                        in_book_only=True)
        outline = self.generate_chapter_outline(speaker, tenant_id=tenant_id)
        if tenant_id:
            self.match_drafts(outline, self.db.get_chapter_drafts(tenant_id=tenant_id))
        written = [c for c in outline if c.get("draft") and not c.get("draft_stale")]

        words, photos, qrs = 0, 0, 0
        for c in outline:
            if c.get("draft"):
                words += len((c["draft"].get("content") or "").split())
            for mid in c.get("uncovered_ids", c["memory_ids"]):
                m = self.db.get_memory_by_id(mid, tenant_id=tenant_id)
                story = self.db.get_story_by_id(m["story_id"], tenant_id=tenant_id)                     if m and m.get("story_id") else None
                if story:
                    words += len(((story.get("corrected_transcript") or story.get("transcript")
                                   or "")).split())
        if tenant_id:
            conn = self.db._get_connection()
            try:
                photos = conn.execute(
                    "SELECT COUNT(*) FROM stories WHERE tenant_id = ? AND photo_id IS NOT NULL "
                    "AND COALESCE(photo_in_book, 1) = 1", (tenant_id,)).fetchone()[0]
                qrs = conn.execute(
                    "SELECT COUNT(*) FROM stories WHERE tenant_id = ? AND COALESCE(audio_s3_key, '') != '' "
                    "AND COALESCE(qr_in_book, 1) = 1", (tenant_id,)).fetchone()[0]
            finally:
                if not self.db._conn:
                    conn.close()
        est_pages = round(6 + 0.5 * len(outline) + words / 300 + 0.6 * photos + 0.2 * qrs)             if outline else 0

        return {
            "total_memories": len(memories),
            "total_chapters_outlined": len(outline),
            "chapters_ready": len(written),
            "estimated_pages": est_pages,
            "target_pages": 175,
            "percent_complete": int(100 * len(written) / len(outline)) if outline else 0,
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
            mem = self.db.get_memory_by_id(mid, tenant_id=tenant_id)
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
            story = self.db.get_story_by_id(story_id, tenant_id=tenant_id)
            if not story or not story.get("photo_id"):
                continue
            if not story.get("photo_in_book", 1):
                continue
            photo = self.db.get_photo_by_id(story["photo_id"], tenant_id=tenant_id)
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
            # Prefer corrected transcript over stale memory text
            text = mem.get("text", mem.get("text_summary", ""))
            story_id = mem.get("story_id")
            if story_id:
                story = self.db.get_story_by_id(story_id, tenant_id=tenant_id)
                if story:
                    corrected = story.get("corrected_transcript")
                    if corrected and corrected.strip():
                        text = corrected
                    elif story.get("transcript"):
                        text = story["transcript"]
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

        # Also collect unlinked photos (in_book=1, no story) that fit this chapter's time range
        if tenant_id:
            import re as _re
            try:
                conn = self.db._get_connection()
                # Photos flow into the book regardless — a caption is nice but a
                # date alone is enough to place the picture (with its QR).
                unlinked_photos = conn.execute("""
                    SELECT id, caption, date_taken, tags
                    FROM photos WHERE tenant_id = ? AND in_book = 1
                    AND (story_id IS NULL OR story_id = 0)
                    AND ((caption IS NOT NULL AND caption != '')
                         OR (date_taken IS NOT NULL AND date_taken != ''))
                """, (tenant_id,)).fetchall()
                for up in unlinked_photos:
                    caption = up[1] or ""
                    # Extract year from caption or date_taken
                    photo_year = None
                    for source in [up[2] or "", caption]:
                        yr_match = _re.search(r'(19\d{2}|20\d{2})', str(source))
                        if yr_match:
                            photo_year = int(yr_match.group(1))
                            break
                    # Try age-based clues in caption (e.g., "6th grade" = ~age 11)
                    if not photo_year and owner_birth_year:
                        grade_match = _re.search(r'(\d+)(?:st|nd|rd|th)\s*grade', caption.lower())
                        if grade_match:
                            grade = int(grade_match.group(1))
                            photo_year = owner_birth_year + 5 + grade

                    # Check if this photo fits the chapter's time range
                    chapter_years = [m.get("estimated_year") for m in memories if m.get("estimated_year")]
                    if chapter_years and photo_year:
                        ch_min = min(chapter_years) - 3
                        ch_max = max(chapter_years) + 3
                        if not (ch_min <= photo_year <= ch_max):
                            continue
                    elif chapter_years and not photo_year:
                        # No year on photo — skip for now, will catch in a later chapter or appendix
                        continue

                    people_in_photo = []
                    if up[3]:
                        try:
                            import json as _json
                            tags = _json.loads(up[3]) if isinstance(up[3], str) else up[3]
                            people_in_photo = [t for t in tags if isinstance(t, str)]
                        except (ValueError, TypeError):
                            pass

                    available_photos.append({
                        "photo_id": up[0],
                        "story_id": None,
                        "caption": caption,
                        "date_taken": up[2] or "",
                        "photo_year": photo_year,
                        "people": people_in_photo,
                    })
            except Exception as e:
                logger.warning(f"Could not load unlinked photos: {e}")

        # Build photo placement instructions
        photo_block = ""
        if available_photos:
            photo_lines = []
            for p in available_photos:
                if p.get("story_id"):
                    line = f"  - [PHOTO:{p['story_id']}]"
                else:
                    line = f"  - [PHOTO:p{p['photo_id']}]"
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
- Format: [PHOTO:story_id] or [PHOTO:p123] on a line by itself between paragraphs
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

        # Build owner profile block
        owner_block = ""
        if tenant_id:
            try:
                conn = self.db._get_connection()
                owner_prof = conn.execute(
                    "SELECT name, familiar_name, hometown, birth_year, location_city FROM user_profiles WHERE tenant_id = ? LIMIT 1",
                    (tenant_id,)
                ).fetchone()
                if owner_prof:
                    oname = owner_prof[1] or owner_prof[0] or speaker or "the owner"
                    parts = [f"The subject of this book is {oname}."]
                    if owner_prof[3]:
                        parts.append(f"Born in {owner_prof[3]}.")
                    if owner_prof[2]:
                        parts.append(f"Grew up in {owner_prof[2]}.")
                    if owner_prof[4] and owner_prof[4] != owner_prof[2]:
                        parts.append(f"Currently lives in {owner_prof[4]}.")
                    owner_block = "\n" + " ".join(parts) + "\n"
            except Exception:
                pass

        n = len(memories)
        prompt = f"""You are writing a chapter of a family legacy book.
Chapter {chapter.get('chapter_number', '?')}: "{chapter['title']}"
Theme: {chapter['bucket'].replace('_', ' ')}
Life phase: {chapter['life_phase']}
{owner_block}{timeline_block}{family_block}{continuity_block}
Here are the {n} memories to weave into this chapter (sorted chronologically):

{chr(10).join(memory_texts)}
{photo_block}
EVERY ONE of the {n} memories above MUST appear in the chapter with its own
specific people, places and details. Do not skip a memory, and do not fold two
memories into one vague sentence. This is someone's family record — a missing
memory is a lost memory.

Write a warm, narrative chapter ({max(7, n + 2)}-{max(10, n + 4)} paragraphs) that:
- Weaves these memories into a cohesive story in chronological order
- Preserves the speaker's voice and emotional tone
- MULTIPLE PERSPECTIVES: when two or more people remember the SAME event, day, or
  photo differently, honor each person's version distinctly and attribute it by
  name (e.g. "Her brother remembers the wedding as a chaotic, joyful blur, while
  her sister-in-law recalls the quiet moment before the ceremony..."). NEVER force
  contradictory memories into a single 'official' account — the differing
  rememberances ARE the richness. Let them stand side by side.
- Adds gentle transitions between memories
- Opens with a scene-setting paragraph grounded in time and place
- Closes with a reflective paragraph
- Uses second person sparingly, mostly third person narrative
- Keeps a blue-collar, honest, heartfelt tone
- When timeline dates are available, ground the narrative in specific years or decades (e.g. "It was the summer of '58..." instead of "Back then...")
- When owner age is given, use it to anchor the perspective (e.g. "At nine years old, the world still felt enormous...")
- Use family birth years to anchor events (e.g. if Brooklyn was born in 2018 and the story mentions her gymnastics, that's ~2024-2026)
- Previous chapters are listed only for continuity — do not retell THEIR stories,
  but every memory listed above belongs in THIS chapter and must be told here
- ONLY place [PHOTO:story_id] markers if photos are listed above as "Available photos for this chapter". Do NOT invent photo markers. If no photos are available, do not include any [PHOTO:...] markers at all.

Write the chapter now:"""

        import asyncio
        try:
            result = await asyncio.to_thread(self._call_chapter_openai, prompt)
        except Exception as e:
            logger.error(f"Chapter generation failed: {e}")
            return None
        if not result:
            return None
        result = strip_heading(result)

        # Coverage check: a second, cheap model confirms every memory made it
        # into the prose. One retry naming what was skipped; anything still
        # missing is recorded so the PDF prints it verbatim after the chapter.
        chapter["missing_memory_ids"] = []
        try:
            missing = await asyncio.to_thread(self._find_missing_memories, result, memory_texts)
            if missing:
                names = ", ".join(f"Memory {i}" for i in missing)
                retry = (prompt + f"\n\nIMPORTANT: a previous attempt left out {names}. "
                         "Include every one of them this time.")
                second = await asyncio.to_thread(self._call_chapter_openai, retry)
                if second:
                    second = strip_heading(second)
                    missing2 = await asyncio.to_thread(self._find_missing_memories, second, memory_texts)
                    if len(missing2) <= len(missing):
                        result, missing = second, missing2
            chapter["missing_memory_ids"] = [memories[i - 1]["id"] for i in missing]
            if missing:
                logger.warning(f"Chapter '{chapter['title']}': memories {chapter['missing_memory_ids']} "
                               "not in prose after retry — will print verbatim")
        except Exception as e:
            # Keep the draft; marking everything missing would print the whole
            # chapter twice. The coverage page still lists the chapter's stories.
            logger.error(f"Coverage check failed for '{chapter['title']}': {e}")

        return result

    def _find_missing_memories(self, chapter_text: str, memory_texts: List[str]) -> List[int]:
        """Return the 1-based numbers of memories whose specific content is
        absent from chapter_text.

        Evidence-based: for every memory the auditor must quote the chapter
        sentence that tells it. A memory counts as missing only when it can't
        — and a "present" verdict whose quote isn't really in the chapter is
        overruled. (gpt-4o-mini asked for a bare list flagged 8 of 10 stories
        as missing from a chapter that plainly told them.)"""
        listing = "\n\n".join(t[:1200] for t in memory_texts)
        response = self.followup_gen._client.chat.completions.create(
            model=os.getenv("POLLY_COVERAGE_MODEL", "gpt-4o"),
            messages=[
                {"role": "system", "content": (
                    "You audit a family book chapter against its numbered source memories. "
                    "For EVERY memory, find the sentence in the chapter that tells it — "
                    "its specific event, people or details; paraphrase counts. Return JSON: "
                    '{"memories": [{"n": <memory number>, "quote": "<exact sentence copied '
                    'from the chapter, or empty if none tells it>"}]}. '
                    "Only leave quote empty when no sentence in the chapter tells that memory.")},
                {"role": "user", "content": f"SOURCE MEMORIES:\n{listing}\n\nCHAPTER:\n{chapter_text}"},
            ],
            temperature=0,
            max_tokens=2500,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(response.choices[0].message.content)
        flat = " ".join(chapter_text.split()).lower()
        found = set()
        for item in parsed.get("memories", []):
            quote = " ".join(str(item.get("quote") or "").split()).lower().strip(' ."\'')
            # the quote must really be in the chapter (first 40 chars is enough
            # to tolerate small copy differences at the end)
            if len(quote) >= 15 and quote[:40] in flat:
                try:
                    found.add(int(item.get("n")))
                except (TypeError, ValueError):
                    pass
        return [i for i in range(1, len(memory_texts) + 1) if i not in found]

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

    async def write_chapter(self, chapter: Dict, tenant_id: int, outline: List[Dict]) -> Optional[int]:
        """Write (or rewrite) one chapter and save it. Returns the draft id.

        The one path every writer uses — the Regenerate button, the
        background refresher and scripts — so they all behave the same:
        coverage-checked prose, a real title for generic chapters, a
        continuity summary, and a rewrite that keeps the version it replaces.
        """
        previous_summaries = [c["draft"]["summary"] for c in outline
                              if c["chapter_number"] < chapter["chapter_number"]
                              and c.get("draft") and c["draft"].get("summary")]
        content = await self.generate_chapter_draft(
            chapter, tenant_id=tenant_id,
            previous_summaries=previous_summaries or None)
        if not content:
            return None

        title = chapter["title"]
        if title.endswith("(more)") or title in ("More Memories", "Chapter"):
            taken = {c["title"] for c in outline if c is not chapter}
            title = await self._suggest_title(content, taken) or title
        summary = await self.generate_chapter_summary(content)
        missing = json.dumps(chapter.get("missing_memory_ids", []))
        memory_ids = json.dumps(chapter.get("memory_ids", []))
        placements = json.dumps(self.placements_of(chapter.get("memory_ids", []), tenant_id))

        if chapter.get("draft_id"):
            conn = self.db._get_connection()
            try:
                # previous_content = content reads the OLD value (SQLite SET semantics)
                conn.execute("""
                    UPDATE chapter_drafts
                    SET previous_content = content, content = ?, title = ?, bucket = ?,
                        life_phase = ?, memory_ids = ?, missing_memory_ids = ?, summary = ?,
                        chapter_number = ?, hand_edited = 0, placements = ?,
                        created_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND tenant_id = ?
                """, (content, title, chapter["bucket"], chapter["life_phase"], memory_ids,
                      missing, summary, chapter["chapter_number"], placements,
                      chapter["draft_id"], tenant_id))
                conn.commit()
            finally:
                if not self.db._conn:
                    conn.close()
            draft_id = chapter["draft_id"]
        else:
            draft_id = self.db.save_chapter_draft(
                chapter_number=chapter["chapter_number"], title=title,
                bucket=chapter["bucket"], life_phase=chapter["life_phase"],
                memory_ids=memory_ids, content=content, tenant_id=tenant_id,
                missing_memory_ids=missing)
            if summary:
                self.db.update_chapter_summary(draft_id, summary)
            conn = self.db._get_connection()
            try:
                conn.execute("UPDATE chapter_drafts SET placements = ? WHERE id = ?",
                             (placements, draft_id))
                conn.commit()
            finally:
                if not self.db._conn:
                    conn.close()
        chapter["title"] = title
        logger.info(f"Wrote chapter '{title}' for tenant {tenant_id} "
                    f"({len(chapter.get('memory_ids', []))} memories, missing {missing})")
        return draft_id

    async def recheck_coverage(self, draft: Dict, tenant_id: int) -> List[int]:
        """Re-audit a saved draft's prose against its memories. Returns the
        ids of memories its prose does not tell."""
        import asyncio
        mems = [m for m in (self.db.get_memory_by_id(i, tenant_id=tenant_id)
                            for i in _draft_ids(draft)) if m]
        mems.sort(key=lambda m: (m.get("estimated_year") or 9999, m.get("id", 0)))
        texts = []
        for i, m in enumerate(mems, 1):
            story = self.db.get_story_by_id(m["story_id"], tenant_id=tenant_id) if m.get("story_id") else None
            text = ((story or {}).get("corrected_transcript") or (story or {}).get("transcript")
                    or m.get("text") or "")
            texts.append(f"Memory {i} ({m.get('speaker') or 'someone'}): {text}")
        missing = await asyncio.to_thread(self._find_missing_memories,
                                          strip_heading(draft.get("content") or ""), texts)
        return [mems[i - 1]["id"] for i in missing]

    def placements_of(self, memory_ids: List[int], tenant_id: int) -> Dict[str, str]:
        """{memory_id: "bucket/life_phase"} as the memories are sorted now."""
        out = {}
        for i in memory_ids:
            m = self.db.get_memory_by_id(i, tenant_id=tenant_id)
            if m:
                out[str(i)] = _placement(m)
        return out

    def thin_spots(self, tenant_id: int, min_stories: int = 5) -> List[Dict]:
        """Where the book needs stories, thinnest first: chapters with fewer
        than min_stories, then earlier life stages with no chapter at all
        (only stages the owner has already lived)."""
        outline = self.generate_chapter_outline(tenant_id=tenant_id)
        spots = [{"title": c["title"], "bucket": c["bucket"], "life_phase": c["life_phase"],
                  "memory_ids": c["memory_ids"], "count": c["memory_count"]}
                 for c in outline if c["memory_count"] < min_stories
                 and c["life_phase"] != "unknown"]
        spots.sort(key=lambda s: (s["count"], PHASE_ORDER.index(s["life_phase"])
                                  if s["life_phase"] in PHASE_ORDER else 99))
        born = self._owner_birth_year(tenant_id)
        if born:
            from datetime import datetime
            lived = phase_for_age(datetime.now().year - born)
            have = {c["life_phase"] for c in outline}
            for p in PHASE_ORDER[:PHASE_ORDER.index(lived) + 1]:
                if p not in have:
                    spots.insert(0, {"title": None, "bucket": None, "life_phase": p,
                                     "memory_ids": [], "count": 0})
        return spots

    def _owner_birth_year(self, tenant_id: int) -> Optional[int]:
        conn = self.db._get_connection()
        try:
            row = conn.execute("SELECT birth_year FROM user_profiles WHERE tenant_id = ? LIMIT 1",
                               (tenant_id,)).fetchone()
            return row[0] if row and row[0] else None
        finally:
            if not self.db._conn:
                conn.close()

    def gap_question(self, spot: Dict, tenant_id: int, family: str = "") -> Optional[str]:
        """One warm question that invites a NEW story for a thin chapter
        (or an untold life stage), written from what it already holds."""
        told = []
        for mid in spot["memory_ids"][:8]:
            m = self.db.get_memory_by_id(mid, tenant_id=tenant_id)
            if m:
                told.append("- " + ((m.get("text_summary") or "").strip()
                                    or (m.get("text") or "")[:200].strip()))
        stage = PHASE_LABELS_PLAIN.get(spot["life_phase"], spot["life_phase"])
        born = self._owner_birth_year(tenant_id)
        when = ""
        spans = {"childhood": (0, 12), "adolescence": (13, 18), "young_adult": (19, 30),
                 "adult": (31, 50), "midlife": (51, 70)}
        if born and spot["life_phase"] in spans:
            from datetime import datetime
            a, b = spans[spot["life_phase"]]
            b = min(b, datetime.now().year - born)   # never a range into the future
            when = f" (about {born + a}-{born + b}, ages {a}-{b})"
        target = (f'the chapter "{spot["title"]}", about the storyteller\'s {stage}{when}'
                  f'{", theme: " + spot["bucket"].replace("_", " ") if spot.get("bucket") else ""}'
                  if spot["title"] else f"the storyteller's {stage}{when}, which has no stories yet")
        prompt = (
            f"You help someone record their family legacy book. {family}\n\n"
            f"Their book needs more stories for {target}.\n"
            + (("Stories already told there (do NOT ask about these again):\n"
                + "\n".join(told) + "\n") if told else "")
            + ("\nThis is a reflections chapter: ask for a lesson, belief or piece of advice "
               "they would pass on today — not a past event.\n"
               if spot["life_phase"] == "reflection" else
               "\nAsk about a specific moment from that time of life, not a general feeling.\n")
            + "\nWrite ONE question the way a curious grandchild would ask it: plain, "
              "friendly, everyday words, one thing at a time (no 'and how did that...' add-ons). "
              "Speak to them as 'you'. Name a family member only if the question is really "
              "about that person. Under 25 words. Reply with the question only.")

        response = self.followup_gen._client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=80, temperature=0.8)
        q = response.choices[0].message.content.strip().strip('"').strip()
        return q or None

    async def _suggest_title(self, content: str, taken: set) -> Optional[str]:
        """A short, warm title for a chapter whose template title is generic."""
        import asyncio

        def call():
            response = self.followup_gen._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": (
                    "Give this chapter of a family legacy book a warm, specific title of "
                    "2 to 5 words, drawn from what it is about. Do not use any of these: "
                    f"{', '.join(sorted(taken)) or 'none'}. Reply with the title only.\n\n"
                    + content[:4000])}],
                max_tokens=20, temperature=0.4)
            return response.choices[0].message.content.strip().strip('"\'*').strip()
        try:
            title = await asyncio.to_thread(call)
            return title if title and len(title) <= 60 and title not in taken else None
        except Exception as e:
            logger.warning(f"Title suggestion failed: {e}")
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
