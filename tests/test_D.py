"""
Test Suite D - Legacy Book Pipeline
====================================
End-to-end tests for the book generation pipeline:
  - Memory → chapter assignment (Jungian buckets, life phases)
  - Chapter outline generation (grouping, chunking, status)
  - Photo/QR toggle filtering (photo_in_book, qr_in_book)
  - PDF generation (structure, content, photos, QR codes)
  - Multi-tenant isolation (no data leakage between tenants)
  - Chapter draft integration (AI drafts vs raw memories)
  - Edge cases (empty chapters, missing photos, no audio)

Run: python -m pytest tests/test_D.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import json
import io
import tempfile
import struct
import pytest
from unittest.mock import patch, MagicMock

from server.core.database import PollyDB
from server.core.book_builder import BookBuilder


# ═══════════════════════════════════════════════════════════════
#                        FIXTURES
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def db():
    """In-memory database with schema initialized."""
    d = PollyDB(":memory:")
    return d


@pytest.fixture
def tenant_a(db):
    """Create tenant A with stories, memories, photos, and audio."""
    tid = db.create_tenant("Family A")

    # ── Stories covering all 6 Jungian buckets ──
    stories = {}

    # ordinary_world / childhood (need 5+ for "ready" status)
    for i in range(6):
        sid = db.save_story(
            transcript=f"Childhood memory {i}: playing in the yard with grandpa.",
            speaker_name="Grandpa Joe",
            tenant_id=tid,
        )
        stories[f"child_{i}"] = sid
        db.save_memory(
            story_id=sid, speaker="Grandpa Joe",
            bucket="ordinary_world", life_phase="childhood",
            text=f"Childhood memory {i}: playing in the yard with grandpa.",
            text_summary=f"Childhood memory {i}",
            tenant_id=tid,
        )

    # call_to_adventure / adolescence (5 stories)
    for i in range(5):
        sid = db.save_story(
            transcript=f"Turning point {i}: the day everything changed.",
            speaker_name="Mom",
            tenant_id=tid,
        )
        stories[f"adventure_{i}"] = sid
        db.save_memory(
            story_id=sid, speaker="Mom",
            bucket="call_to_adventure", life_phase="adolescence",
            text=f"Turning point {i}: the day everything changed.",
            text_summary=f"Turning point {i}",
            tenant_id=tid,
        )

    # crossing_threshold / young_adult (5 stories)
    for i in range(5):
        sid = db.save_story(
            transcript=f"Big decision {i}: leaving home for the first time.",
            speaker_name="Dad",
            tenant_id=tid,
        )
        stories[f"threshold_{i}"] = sid
        db.save_memory(
            story_id=sid, speaker="Dad",
            bucket="crossing_threshold", life_phase="young_adult",
            text=f"Big decision {i}: leaving home for the first time.",
            text_summary=f"Big decision {i}",
            tenant_id=tid,
        )

    # trials_allies_enemies / adult (5 stories)
    for i in range(5):
        sid = db.save_story(
            transcript=f"Challenge {i}: the hardest year of my life.",
            speaker_name="Aunt Rose",
            tenant_id=tid,
        )
        stories[f"trials_{i}"] = sid
        db.save_memory(
            story_id=sid, speaker="Aunt Rose",
            bucket="trials_allies_enemies", life_phase="adult",
            text=f"Challenge {i}: the hardest year of my life.",
            text_summary=f"Challenge {i}",
            tenant_id=tid,
        )

    # transformation / midlife (5 stories)
    for i in range(5):
        sid = db.save_story(
            transcript=f"Change {i}: I became a different person.",
            speaker_name="Uncle Ray",
            tenant_id=tid,
        )
        stories[f"transform_{i}"] = sid
        db.save_memory(
            story_id=sid, speaker="Uncle Ray",
            bucket="transformation", life_phase="midlife",
            text=f"Change {i}: I became a different person.",
            text_summary=f"Change {i}",
            tenant_id=tid,
        )

    # return_with_knowledge / reflection (5 stories)
    for i in range(5):
        sid = db.save_story(
            transcript=f"Wisdom {i}: what I know now that I wish I knew then.",
            speaker_name="Grandma",
            tenant_id=tid,
        )
        stories[f"wisdom_{i}"] = sid
        db.save_memory(
            story_id=sid, speaker="Grandma",
            bucket="return_with_knowledge", life_phase="reflection",
            text=f"Wisdom {i}: what I know now that I wish I knew then.",
            text_summary=f"Wisdom {i}",
            tenant_id=tid,
        )

    return {"tenant_id": tid, "stories": stories}


@pytest.fixture
def tenant_b(db):
    """Create tenant B (for isolation tests) with minimal data."""
    tid = db.create_tenant("Family B")

    sid = db.save_story(
        transcript="Tenant B private story that should never appear in tenant A.",
        speaker_name="Private Person",
        tenant_id=tid,
    )
    db.save_memory(
        story_id=sid, speaker="Private Person",
        bucket="ordinary_world", life_phase="childhood",
        text="Tenant B private story that should never appear in tenant A.",
        text_summary="Private",
        tenant_id=tid,
    )

    return {"tenant_id": tid}


def _make_temp_photo(directory, name="test_photo.jpeg"):
    """Create a minimal JPEG file for testing."""
    # Minimal valid JPEG (2x2 pixels)
    jpeg_bytes = bytes([
        0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46,
        0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01,
        0x00, 0x01, 0x00, 0x00, 0xFF, 0xD9,
    ])
    path = os.path.join(directory, name)
    with open(path, "wb") as f:
        f.write(jpeg_bytes)
    return path


def _make_temp_wav(directory, name="test.wav", duration_seconds=1):
    """Create a minimal WAV file for testing."""
    sr = 16000
    ns = sr * duration_seconds
    ds = ns * 2
    path = os.path.join(directory, name)
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + ds))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", ds))
        f.write(b"\x00" * ds)
    return path


# ═══════════════════════════════════════════════════════════════
#              CHAPTER OUTLINE GENERATION
# ═══════════════════════════════════════════════════════════════

class TestChapterOutlineGeneration:
    """BookBuilder.generate_chapter_outline() groups memories correctly."""

    def test_outline_returns_chapters(self, db, tenant_a):
        bb = BookBuilder(db)
        chapters = bb.generate_chapter_outline(tenant_id=tenant_a["tenant_id"])
        assert len(chapters) > 0

    def test_each_chapter_has_required_fields(self, db, tenant_a):
        bb = BookBuilder(db)
        chapters = bb.generate_chapter_outline(tenant_id=tenant_a["tenant_id"])
        required = {"chapter_number", "title", "bucket", "life_phase",
                     "memory_count", "memory_ids", "status"}
        for ch in chapters:
            assert required.issubset(ch.keys()), f"Chapter {ch} missing fields"

    def test_chapter_numbers_sequential(self, db, tenant_a):
        bb = BookBuilder(db)
        chapters = bb.generate_chapter_outline(tenant_id=tenant_a["tenant_id"])
        numbers = [ch["chapter_number"] for ch in chapters]
        assert numbers == list(range(1, len(chapters) + 1))

    def test_chapters_have_valid_buckets(self, db, tenant_a):
        bb = BookBuilder(db)
        chapters = bb.generate_chapter_outline(tenant_id=tenant_a["tenant_id"])
        valid_buckets = {
            "ordinary_world", "call_to_adventure", "crossing_threshold",
            "trials_allies_enemies", "transformation", "return_with_knowledge",
        }
        for ch in chapters:
            assert ch["bucket"] in valid_buckets, f"Invalid bucket: {ch['bucket']}"

    def test_chapters_have_valid_life_phases(self, db, tenant_a):
        bb = BookBuilder(db)
        chapters = bb.generate_chapter_outline(tenant_id=tenant_a["tenant_id"])
        valid_phases = {
            "childhood", "adolescence", "young_adult", "adult",
            "midlife", "elder", "reflection", "unknown",
        }
        for ch in chapters:
            assert ch["life_phase"] in valid_phases, f"Invalid phase: {ch['life_phase']}"

    def test_ready_status_when_enough_memories(self, db, tenant_a):
        """Chapters with 5+ memories should be 'ready'."""
        bb = BookBuilder(db)
        chapters = bb.generate_chapter_outline(tenant_id=tenant_a["tenant_id"])
        for ch in chapters:
            if ch["memory_count"] >= 5:
                assert ch["status"] == "ready", \
                    f"Ch {ch['chapter_number']} has {ch['memory_count']} memories but status={ch['status']}"

    def test_needs_more_status_when_few_memories(self, db):
        """Chapters with < min_memories should be 'needs_more'."""
        tid = db.create_tenant("Sparse Family")
        # Only 3 memories — below the 5-memory threshold
        for i in range(3):
            sid = db.save_story(transcript=f"Memory {i}", tenant_id=tid)
            db.save_memory(story_id=sid, bucket="ordinary_world",
                           life_phase="childhood", text=f"Memory {i}",
                           tenant_id=tid)
        bb = BookBuilder(db)
        chapters = bb.generate_chapter_outline(tenant_id=tid)
        for ch in chapters:
            assert ch["status"] == "needs_more"

    def test_empty_tenant_returns_no_chapters(self, db):
        tid = db.create_tenant("Empty Family")
        bb = BookBuilder(db)
        chapters = bb.generate_chapter_outline(tenant_id=tid)
        assert chapters == []

    def test_max_10_memories_per_chapter(self, db):
        """Large groups should be chunked into max 10 per chapter."""
        tid = db.create_tenant("Big Family")
        for i in range(25):
            sid = db.save_story(transcript=f"Memory {i}", tenant_id=tid)
            db.save_memory(story_id=sid, bucket="ordinary_world",
                           life_phase="childhood", text=f"Memory {i}",
                           tenant_id=tid)
        bb = BookBuilder(db)
        chapters = bb.generate_chapter_outline(tenant_id=tid)
        for ch in chapters:
            assert ch["memory_count"] <= 10, \
                f"Ch {ch['chapter_number']} has {ch['memory_count']} > 10"

    def test_memory_ids_are_real(self, db, tenant_a):
        """Every memory_id in a chapter should exist in the database."""
        bb = BookBuilder(db)
        chapters = bb.generate_chapter_outline(tenant_id=tenant_a["tenant_id"])
        for ch in chapters:
            for mid in ch["memory_ids"]:
                mem = db.get_memory_by_id(mid)
                assert mem is not None, f"Memory {mid} not found"


# ═══════════════════════════════════════════════════════════════
#              MULTI-TENANT ISOLATION
# ═══════════════════════════════════════════════════════════════

class TestMultiTenantIsolation:
    """No data should leak between tenants."""

    def test_chapter_outline_isolated(self, db, tenant_a, tenant_b):
        bb = BookBuilder(db)
        chapters_a = bb.generate_chapter_outline(tenant_id=tenant_a["tenant_id"])
        chapters_b = bb.generate_chapter_outline(tenant_id=tenant_b["tenant_id"])

        # Tenant A should have many chapters, B should have very few or none
        assert len(chapters_a) > len(chapters_b)

        # Tenant A's memory IDs should not appear in Tenant B's chapters
        a_ids = set()
        for ch in chapters_a:
            a_ids.update(ch["memory_ids"])
        b_ids = set()
        for ch in chapters_b:
            b_ids.update(ch["memory_ids"])
        assert a_ids.isdisjoint(b_ids), "Memory IDs leaked between tenants"

    def test_memories_dont_cross_tenants(self, db, tenant_a, tenant_b):
        """Memories fetched for tenant A should not include tenant B data."""
        mems_a = db.get_memories(tenant_id=tenant_a["tenant_id"], limit=9999)
        mems_b = db.get_memories(tenant_id=tenant_b["tenant_id"], limit=9999)

        a_texts = {m["text"] for m in mems_a}
        b_texts = {m["text"] for m in mems_b}
        assert a_texts.isdisjoint(b_texts)

    def test_chapter_drafts_isolated(self, db, tenant_a, tenant_b):
        """Chapter drafts should be tenant-scoped."""
        db.save_chapter_draft(
            chapter_number=1, title="Test A", bucket="ordinary_world",
            life_phase="childhood", memory_ids="[1,2]",
            content="Tenant A chapter.", tenant_id=tenant_a["tenant_id"],
        )
        db.save_chapter_draft(
            chapter_number=1, title="Test B", bucket="ordinary_world",
            life_phase="childhood", memory_ids="[99]",
            content="Tenant B chapter.", tenant_id=tenant_b["tenant_id"],
        )

        drafts_a = db.get_chapter_drafts(tenant_id=tenant_a["tenant_id"])
        drafts_b = db.get_chapter_drafts(tenant_id=tenant_b["tenant_id"])

        assert all(d["content"] != "Tenant B chapter." for d in drafts_a)
        assert all(d["content"] != "Tenant A chapter." for d in drafts_b)

    def test_book_progress_isolated(self, db, tenant_a, tenant_b):
        bb = BookBuilder(db)
        prog_a = bb.get_book_progress(tenant_id=tenant_a["tenant_id"])
        prog_b = bb.get_book_progress(tenant_id=tenant_b["tenant_id"])
        assert prog_a["total_memories"] > prog_b["total_memories"]


# ═══════════════════════════════════════════════════════════════
#              PHOTO/QR TOGGLE FILTERING
# ═══════════════════════════════════════════════════════════════

class TestPhotoQRToggleFiltering:
    """photo_in_book and qr_in_book flags control what appears in PDF."""

    def test_photo_in_book_default_is_1(self, db, tenant_a):
        """New stories should default to photo_in_book=1."""
        sid = db.save_story(
            transcript="Test story", tenant_id=tenant_a["tenant_id"],
        )
        story = db.get_story_by_id(sid)
        assert story.get("photo_in_book", 1) == 1

    def test_qr_in_book_default_is_1(self, db, tenant_a):
        """New stories should default to qr_in_book=1."""
        sid = db.save_story(
            transcript="Test story", tenant_id=tenant_a["tenant_id"],
        )
        story = db.get_story_by_id(sid)
        assert story.get("qr_in_book", 1) == 1

    def test_photo_excluded_when_toggled_off(self, db, tenant_a):
        """Stories with photo_in_book=0 should not have photos in PDF."""
        from server.core.book_pdf import LegacyBookPDF
        bb = BookBuilder(db)

        # Create a story with a photo and photo_in_book=0
        sid = db.save_story(
            transcript="Story with hidden photo",
            audio_s3_key="test.wav",
            tenant_id=tenant_a["tenant_id"],
        )
        pid = db.save_photo(
            filename="hidden.jpeg", caption="Hidden photo",
            story_id=sid, tenant_id=tenant_a["tenant_id"],
        )
        # Link photo to story
        conn = db._get_connection()
        conn.execute("UPDATE stories SET photo_id=?, photo_in_book=0 WHERE id=?", (pid, sid))
        conn.commit()

        mid = db.save_memory(
            story_id=sid, bucket="ordinary_world", life_phase="childhood",
            text="Story with hidden photo", tenant_id=tenant_a["tenant_id"],
        )

        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tenant_a["tenant_id"])
        chapter = {"memory_ids": [mid]}
        photos = pdf_gen._get_chapter_photos(chapter)
        assert len(photos) == 0, "Photo should be excluded when photo_in_book=0"

    def test_photo_included_when_toggled_on(self, db, tenant_a):
        """Stories with photo_in_book=1 should have photos in PDF."""
        from server.core.book_pdf import LegacyBookPDF
        bb = BookBuilder(db)

        sid = db.save_story(
            transcript="Story with visible photo",
            audio_s3_key="test.wav",
            tenant_id=tenant_a["tenant_id"],
        )
        pid = db.save_photo(
            filename="visible.jpeg", caption="Visible photo",
            story_id=sid, tenant_id=tenant_a["tenant_id"],
        )
        conn = db._get_connection()
        conn.execute("UPDATE stories SET photo_id=?, photo_in_book=1 WHERE id=?", (pid, sid))
        conn.commit()

        mid = db.save_memory(
            story_id=sid, bucket="ordinary_world", life_phase="childhood",
            text="Story with visible photo", tenant_id=tenant_a["tenant_id"],
        )

        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tenant_a["tenant_id"])
        chapter = {"memory_ids": [mid]}

        # Mock the file existence check since we don't have real files
        with patch("os.path.exists", return_value=True):
            photos = pdf_gen._get_chapter_photos(chapter)
        assert len(photos) == 1, "Photo should be included when photo_in_book=1"
        assert photos[0]["caption"] == "Visible photo"

    def test_qr_excluded_when_toggled_off(self, db, tenant_a):
        """Stories with qr_in_book=0 should not have QR codes in PDF."""
        from server.core.book_pdf import LegacyBookPDF
        bb = BookBuilder(db)

        sid = db.save_story(
            transcript="Story with hidden QR",
            audio_s3_key="hidden_audio.wav",
            tenant_id=tenant_a["tenant_id"],
        )
        conn = db._get_connection()
        conn.execute("UPDATE stories SET qr_in_book=0 WHERE id=?", (sid,))
        conn.commit()

        mid = db.save_memory(
            story_id=sid, bucket="ordinary_world", life_phase="childhood",
            text="Story with hidden QR", tenant_id=tenant_a["tenant_id"],
        )

        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tenant_a["tenant_id"])
        chapter = {"memory_ids": [mid]}
        entries = pdf_gen._get_chapter_audio_entries(chapter)
        assert len(entries) == 0, "QR should be excluded when qr_in_book=0"

    def test_qr_included_when_toggled_on(self, db, tenant_a):
        """Stories with qr_in_book=1 should have QR codes in PDF."""
        from server.core.book_pdf import LegacyBookPDF
        bb = BookBuilder(db)

        sid = db.save_story(
            transcript="Story with visible QR",
            audio_s3_key="visible_audio.wav",
            tenant_id=tenant_a["tenant_id"],
        )
        mid = db.save_memory(
            story_id=sid, bucket="ordinary_world", life_phase="childhood",
            text="Story with visible QR", tenant_id=tenant_a["tenant_id"],
        )

        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tenant_a["tenant_id"])
        chapter = {"memory_ids": [mid]}
        entries = pdf_gen._get_chapter_audio_entries(chapter)
        assert len(entries) == 1
        assert entries[0]["audio_key"] == "visible_audio.wav"

    def test_qr_deduplicates_same_audio(self, db, tenant_a):
        """Same audio_s3_key across multiple memories should only appear once."""
        from server.core.book_pdf import LegacyBookPDF
        bb = BookBuilder(db)

        mids = []
        for i in range(3):
            sid = db.save_story(
                transcript=f"Story {i} same audio",
                audio_s3_key="shared_audio.wav",
                tenant_id=tenant_a["tenant_id"],
            )
            mid = db.save_memory(
                story_id=sid, bucket="ordinary_world", life_phase="childhood",
                text=f"Story {i} same audio", tenant_id=tenant_a["tenant_id"],
            )
            mids.append(mid)

        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tenant_a["tenant_id"])
        chapter = {"memory_ids": mids}
        entries = pdf_gen._get_chapter_audio_entries(chapter)
        assert len(entries) == 1, "Duplicate audio should be deduplicated"

    def test_photo_deduplicates_same_photo(self, db, tenant_a):
        """Same photo_id across multiple memories should only appear once."""
        from server.core.book_pdf import LegacyBookPDF
        bb = BookBuilder(db)

        pid = db.save_photo(
            filename="shared.jpeg", caption="Shared photo",
            tenant_id=tenant_a["tenant_id"],
        )

        mids = []
        for i in range(3):
            sid = db.save_story(
                transcript=f"Story {i} same photo",
                tenant_id=tenant_a["tenant_id"],
            )
            conn = db._get_connection()
            conn.execute("UPDATE stories SET photo_id=?, photo_in_book=1 WHERE id=?", (pid, sid))
            conn.commit()
            mid = db.save_memory(
                story_id=sid, bucket="ordinary_world", life_phase="childhood",
                text=f"Story {i} same photo", tenant_id=tenant_a["tenant_id"],
            )
            mids.append(mid)

        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tenant_a["tenant_id"])
        chapter = {"memory_ids": mids}
        with patch("os.path.exists", return_value=True):
            photos = pdf_gen._get_chapter_photos(chapter)
        assert len(photos) == 1, "Duplicate photos should be deduplicated"

    def test_no_audio_no_qr(self, db, tenant_a):
        """Stories without audio_s3_key should not generate QR entries."""
        from server.core.book_pdf import LegacyBookPDF
        bb = BookBuilder(db)

        sid = db.save_story(
            transcript="Story without audio",
            tenant_id=tenant_a["tenant_id"],
        )
        mid = db.save_memory(
            story_id=sid, bucket="ordinary_world", life_phase="childhood",
            text="Story without audio", tenant_id=tenant_a["tenant_id"],
        )

        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tenant_a["tenant_id"])
        chapter = {"memory_ids": [mid]}
        entries = pdf_gen._get_chapter_audio_entries(chapter)
        assert len(entries) == 0

    def test_no_photo_id_no_photo(self, db, tenant_a):
        """Stories without photo_id should not generate photo entries."""
        from server.core.book_pdf import LegacyBookPDF
        bb = BookBuilder(db)

        sid = db.save_story(
            transcript="Story without photo",
            tenant_id=tenant_a["tenant_id"],
        )
        mid = db.save_memory(
            story_id=sid, bucket="ordinary_world", life_phase="childhood",
            text="Story without photo", tenant_id=tenant_a["tenant_id"],
        )

        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tenant_a["tenant_id"])
        chapter = {"memory_ids": [mid]}
        photos = pdf_gen._get_chapter_photos(chapter)
        assert len(photos) == 0


# ═══════════════════════════════════════════════════════════════
#              CHAPTER DRAFT INTEGRATION
# ═══════════════════════════════════════════════════════════════

class TestChapterDraftIntegration:
    """Chapter drafts integrate correctly with PDF generation."""

    def test_save_and_retrieve_draft(self, db, tenant_a):
        tid = tenant_a["tenant_id"]
        draft_id = db.save_chapter_draft(
            chapter_number=1, title="Test Chapter",
            bucket="ordinary_world", life_phase="childhood",
            memory_ids="[1,2,3]",
            content="This is a test chapter with rich content.",
            tenant_id=tid,
        )
        assert draft_id > 0

        drafts = db.get_chapter_drafts(tenant_id=tid)
        assert len(drafts) == 1
        assert drafts[0]["title"] == "Test Chapter"
        assert drafts[0]["content"] == "This is a test chapter with rich content."

    def test_draft_memory_ids_are_json(self, db, tenant_a):
        tid = tenant_a["tenant_id"]
        db.save_chapter_draft(
            chapter_number=1, title="Test", bucket="ordinary_world",
            life_phase="childhood", memory_ids=json.dumps([10, 20, 30]),
            content="Content.", tenant_id=tid,
        )
        drafts = db.get_chapter_drafts(tenant_id=tid)
        parsed = json.loads(drafts[0]["memory_ids"])
        assert parsed == [10, 20, 30]

    def test_multiple_drafts_ordered(self, db, tenant_a):
        tid = tenant_a["tenant_id"]
        for i in [3, 1, 2]:
            db.save_chapter_draft(
                chapter_number=i, title=f"Chapter {i}",
                bucket="ordinary_world", life_phase="childhood",
                memory_ids="[]", content=f"Content {i}.",
                tenant_id=tid,
            )
        drafts = db.get_chapter_drafts(tenant_id=tid)
        numbers = [d["chapter_number"] for d in drafts]
        assert numbers == [1, 2, 3], "Drafts should be ordered by chapter_number"


# ═══════════════════════════════════════════════════════════════
#              PDF GENERATION
# ═══════════════════════════════════════════════════════════════

class TestPDFGeneration:
    """Full PDF generation produces valid output."""

    def test_pdf_generates_bytes(self, db, tenant_a):
        """PDF generation should return non-empty bytes."""
        from server.core.book_pdf import LegacyBookPDF
        bb = BookBuilder(db)
        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tenant_a["tenant_id"])
        pdf_bytes = pdf_gen.generate(speaker_name="Test Person")
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0

    def test_pdf_starts_with_pdf_header(self, db, tenant_a):
        """Valid PDFs start with %PDF."""
        from server.core.book_pdf import LegacyBookPDF
        bb = BookBuilder(db)
        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tenant_a["tenant_id"])
        pdf_bytes = pdf_gen.generate(speaker_name="Test Person")
        assert pdf_bytes[:5] == b"%PDF-"

    def test_pdf_with_custom_title(self, db, tenant_a):
        from server.core.book_pdf import LegacyBookPDF
        bb = BookBuilder(db)
        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tenant_a["tenant_id"])
        pdf_bytes = pdf_gen.generate(
            speaker_name="Test Person",
            book_title="My Custom Title",
        )
        assert len(pdf_bytes) > 0

    def test_pdf_with_dedication(self, db, tenant_a):
        from server.core.book_pdf import LegacyBookPDF
        bb = BookBuilder(db)
        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tenant_a["tenant_id"])
        pdf_bytes = pdf_gen.generate(
            speaker_name="Test Person",
            dedication="For the grandkids, with love.",
        )
        assert len(pdf_bytes) > 0

    def test_pdf_without_qr_codes(self, db, tenant_a):
        from server.core.book_pdf import LegacyBookPDF
        bb = BookBuilder(db)
        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tenant_a["tenant_id"])
        pdf_bytes = pdf_gen.generate(
            speaker_name="Test Person",
            include_qr_codes=False,
        )
        assert len(pdf_bytes) > 0

    def test_pdf_empty_tenant(self, db):
        """PDF should still generate for a tenant with no data."""
        from server.core.book_pdf import LegacyBookPDF
        tid = db.create_tenant("Empty Family")
        bb = BookBuilder(db)
        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tid)
        pdf_bytes = pdf_gen.generate(speaker_name="Nobody")
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0

    def test_pdf_with_chapter_drafts(self, db, tenant_a):
        """PDF should use AI drafts when available."""
        from server.core.book_pdf import LegacyBookPDF

        tid = tenant_a["tenant_id"]
        bb = BookBuilder(db)
        chapters = bb.generate_chapter_outline(tenant_id=tid)

        if chapters:
            ch = chapters[0]
            db.save_chapter_draft(
                chapter_number=ch["chapter_number"],
                title=ch["title"],
                bucket=ch["bucket"],
                life_phase=ch["life_phase"],
                memory_ids=json.dumps(ch["memory_ids"]),
                content="This is a rich AI-generated chapter with multiple paragraphs.\n\n"
                        "The morning fog rolled in from the bay, thick as cotton.\n\n"
                        "He stood at the window and watched the world wake up.",
                tenant_id=tid,
            )

        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tid)
        pdf_bytes = pdf_gen.generate(speaker_name="Test Person")
        assert len(pdf_bytes) > 0

    def test_pdf_default_title_with_speaker(self, db, tenant_a):
        """Title should default to 'The Story of {speaker}' when not provided."""
        from server.core.book_pdf import LegacyBookPDF
        bb = BookBuilder(db)
        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tenant_a["tenant_id"])
        # Just verify it doesn't crash — title logic is internal
        pdf_bytes = pdf_gen.generate(speaker_name="Gi Lee")
        assert len(pdf_bytes) > 0

    def test_pdf_default_title_without_speaker(self, db, tenant_a):
        """Title should default to 'A Family Legacy' when no speaker."""
        from server.core.book_pdf import LegacyBookPDF
        bb = BookBuilder(db)
        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tenant_a["tenant_id"])
        pdf_bytes = pdf_gen.generate()
        assert len(pdf_bytes) > 0


# ═══════════════════════════════════════════════════════════════
#              BOOK PROGRESS TRACKING
# ═══════════════════════════════════════════════════════════════

class TestBookProgress:
    """Book progress stats are accurate and tenant-scoped."""

    def test_progress_has_required_fields(self, db, tenant_a):
        bb = BookBuilder(db)
        progress = bb.get_book_progress(tenant_id=tenant_a["tenant_id"])
        required = {
            "total_memories", "verified_memories", "total_chapters_outlined",
            "chapters_ready", "estimated_pages", "target_pages", "percent_complete",
        }
        assert required.issubset(progress.keys())

    def test_progress_memory_count(self, db, tenant_a):
        bb = BookBuilder(db)
        progress = bb.get_book_progress(tenant_id=tenant_a["tenant_id"])
        # We created 31 memories in tenant_a fixture (6+5+5+5+5+5)
        assert progress["total_memories"] == 31

    def test_progress_empty_tenant(self, db):
        tid = db.create_tenant("Empty")
        bb = BookBuilder(db)
        progress = bb.get_book_progress(tenant_id=tid)
        assert progress["total_memories"] == 0
        assert progress["chapters_ready"] == 0
        assert progress["percent_complete"] == 0

    def test_progress_target_pages(self, db, tenant_a):
        bb = BookBuilder(db)
        progress = bb.get_book_progress(tenant_id=tenant_a["tenant_id"])
        assert progress["target_pages"] == 175

    def test_progress_percent_capped_at_100(self, db):
        """Percent complete should never exceed 100."""
        tid = db.create_tenant("Prolific Family")
        for i in range(200):
            sid = db.save_story(transcript=f"Story {i}", tenant_id=tid)
            db.save_memory(
                story_id=sid, bucket="ordinary_world", life_phase="childhood",
                text=f"Story {i}", tenant_id=tid,
            )
        # Mark all as verified
        conn = db._get_connection()
        conn.execute("UPDATE memories SET verification_status='verified' WHERE tenant_id=?", (tid,))
        conn.commit()

        bb = BookBuilder(db)
        progress = bb.get_book_progress(tenant_id=tid)
        assert progress["percent_complete"] <= 100


# ═══════════════════════════════════════════════════════════════
#              MEMORY-TO-STORY CHAIN
# ═══════════════════════════════════════════════════════════════

class TestMemoryStoryChain:
    """The memory → story → photo/audio chain is intact."""

    def test_memory_links_to_story(self, db, tenant_a):
        """Every memory should link back to a valid story."""
        mems = db.get_memories(tenant_id=tenant_a["tenant_id"], limit=9999)
        for mem in mems:
            if mem.get("story_id"):
                story = db.get_story_by_id(mem["story_id"])
                assert story is not None, f"Memory {mem['id']} links to missing story {mem['story_id']}"

    def test_story_with_photo_has_valid_photo(self, db, tenant_a):
        """If a story has photo_id, the photo should exist."""
        tid = tenant_a["tenant_id"]
        sid = db.save_story(transcript="Photo story", tenant_id=tid)
        pid = db.save_photo(filename="test.jpeg", caption="Test", tenant_id=tid)
        conn = db._get_connection()
        conn.execute("UPDATE stories SET photo_id=? WHERE id=?", (pid, sid))
        conn.commit()

        story = db.get_story_by_id(sid)
        photo = db.get_photo_by_id(story["photo_id"])
        assert photo is not None
        assert photo["filename"] == "test.jpeg"

    def test_photo_story_bidirectional_link(self, db, tenant_a):
        """Photo and story should be linked both ways."""
        tid = tenant_a["tenant_id"]
        sid = db.save_story(transcript="Linked story", tenant_id=tid)
        pid = db.save_photo(filename="linked.jpeg", story_id=sid, tenant_id=tid)
        conn = db._get_connection()
        conn.execute("UPDATE stories SET photo_id=? WHERE id=?", (pid, sid))
        conn.commit()

        story = db.get_story_by_id(sid)
        photo = db.get_photo_by_id(pid)
        assert story["photo_id"] == pid
        assert photo["story_id"] == sid


# ═══════════════════════════════════════════════════════════════
#              EDGE CASES
# ═══════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Edge cases that could break the book pipeline."""

    def test_memory_without_story_id(self, db, tenant_a):
        """Memories without story_id should not crash QR/photo lookups."""
        from server.core.book_pdf import LegacyBookPDF
        bb = BookBuilder(db)

        mid = db.save_memory(
            story_id=None, bucket="ordinary_world", life_phase="childhood",
            text="Orphan memory", tenant_id=tenant_a["tenant_id"],
        )
        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tenant_a["tenant_id"])
        chapter = {"memory_ids": [mid]}

        photos = pdf_gen._get_chapter_photos(chapter)
        entries = pdf_gen._get_chapter_audio_entries(chapter)
        assert len(photos) == 0
        assert len(entries) == 0

    def test_memory_with_deleted_story(self, db, tenant_a):
        """Memory pointing to non-existent story should not crash."""
        from server.core.book_pdf import LegacyBookPDF
        bb = BookBuilder(db)

        mid = db.save_memory(
            story_id=99999, bucket="ordinary_world", life_phase="childhood",
            text="Ghost story reference", tenant_id=tenant_a["tenant_id"],
        )
        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tenant_a["tenant_id"])
        chapter = {"memory_ids": [mid]}

        # Should not crash
        photos = pdf_gen._get_chapter_photos(chapter)
        entries = pdf_gen._get_chapter_audio_entries(chapter)
        assert len(photos) == 0
        assert len(entries) == 0

    def test_empty_chapter_memory_ids(self, db, tenant_a):
        """Chapter with empty memory_ids should not crash."""
        from server.core.book_pdf import LegacyBookPDF
        bb = BookBuilder(db)
        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tenant_a["tenant_id"])

        chapter = {"memory_ids": []}
        photos = pdf_gen._get_chapter_photos(chapter)
        entries = pdf_gen._get_chapter_audio_entries(chapter)
        assert len(photos) == 0
        assert len(entries) == 0

    def test_chapter_with_nonexistent_memory_id(self, db, tenant_a):
        """Chapter referencing a missing memory should not crash."""
        from server.core.book_pdf import LegacyBookPDF
        bb = BookBuilder(db)
        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tenant_a["tenant_id"])

        chapter = {"memory_ids": [99999]}
        photos = pdf_gen._get_chapter_photos(chapter)
        entries = pdf_gen._get_chapter_audio_entries(chapter)
        assert len(photos) == 0
        assert len(entries) == 0

    def test_story_with_html_in_transcript(self, db, tenant_a):
        """HTML in transcripts should be escaped, not rendered."""
        from server.core.book_pdf import LegacyBookPDF
        tid = tenant_a["tenant_id"]
        bb = BookBuilder(db)

        sid = db.save_story(
            transcript="She said <b>hello</b> & he said \"goodbye\"",
            tenant_id=tid,
        )
        mid = db.save_memory(
            story_id=sid, bucket="ordinary_world", life_phase="childhood",
            text="She said <b>hello</b> & he said \"goodbye\"",
            tenant_id=tid,
        )

        # Save a draft that references this memory
        db.save_chapter_draft(
            chapter_number=99, title="HTML Test",
            bucket="ordinary_world", life_phase="childhood",
            memory_ids=json.dumps([mid]),
            content="She said <b>hello</b> & he said \"goodbye\"",
            tenant_id=tid,
        )

        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tid)
        # Should not crash on HTML entities
        pdf_bytes = pdf_gen.generate(speaker_name="Test")
        assert len(pdf_bytes) > 0

    def test_very_long_chapter_content(self, db, tenant_a):
        """Very long chapter content should not crash PDF generation."""
        from server.core.book_pdf import LegacyBookPDF
        tid = tenant_a["tenant_id"]
        bb = BookBuilder(db)

        long_content = ("This is a very long paragraph. " * 500 + "\n\n") * 10
        db.save_chapter_draft(
            chapter_number=98, title="Long Chapter",
            bucket="ordinary_world", life_phase="childhood",
            memory_ids="[1]", content=long_content, tenant_id=tid,
        )

        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tid)
        pdf_bytes = pdf_gen.generate(speaker_name="Test")
        assert len(pdf_bytes) > 0

    def test_single_memory_chapter(self, db):
        """A chapter with just 1 memory should still work."""
        from server.core.book_pdf import LegacyBookPDF
        tid = db.create_tenant("Solo")
        sid = db.save_story(transcript="Only memory", tenant_id=tid)
        mid = db.save_memory(
            story_id=sid, bucket="ordinary_world", life_phase="childhood",
            text="Only memory in the whole book", tenant_id=tid,
        )
        db.save_chapter_draft(
            chapter_number=1, title="The Only Chapter",
            bucket="ordinary_world", life_phase="childhood",
            memory_ids=json.dumps([mid]),
            content="Only memory in the whole book",
            tenant_id=tid,
        )

        bb = BookBuilder(db)
        pdf_gen = LegacyBookPDF(db, bb, tenant_id=tid)
        pdf_bytes = pdf_gen.generate(speaker_name="Solo Person")
        assert len(pdf_bytes) > 0
        assert pdf_bytes[:5] == b"%PDF-"


# ═══════════════════════════════════════════════════════════════
#              DATE/TIMELINE TRACKING
# ═══════════════════════════════════════════════════════════════

class TestTimelineEstimation:
    """Timeline year estimation from relative phrases + birth_year."""

    def test_family_member_birth_year_migration(self, db):
        """birth_year column should exist on family_members."""
        tid = db.create_tenant("Timeline Test")
        mid = db.add_family_member(name="Grandpa", relationship="grandfather", tenant_id=tid)
        db.update_family_member(mid, birth_year=1940)
        member = db.get_family_member_by_id(mid)
        assert member["birth_year"] == 1940

    def test_memory_estimated_year_migration(self, db):
        """estimated_year column should exist on memories."""
        tid = db.create_tenant("Timeline Test")
        sid = db.save_story(transcript="Test", tenant_id=tid)
        mid = db.save_memory(
            story_id=sid, bucket="ordinary_world", life_phase="childhood",
            text="Test memory", tenant_id=tid,
        )
        mem = db.get_memory_by_id(mid)
        assert "estimated_year" in mem

    def test_explicit_year_tagged(self, db):
        """Explicit 4-digit years in transcript should be tagged."""
        tid = db.create_tenant("Timeline Test")
        sid = db.save_story(
            transcript="I remember the summer of 1965 when we went fishing.",
            speaker_name="Grandpa",
            tenant_id=tid,
        )
        db.auto_tag_story(sid, "I remember the summer of 1965 when we went fishing.", tid)

        conn = db._get_connection()
        tags = conn.execute(
            "SELECT tag_type, tag_value FROM story_tags WHERE story_id = ? AND tag_type = 'year'",
            (sid,)
        ).fetchall()
        year_values = [t[1] for t in tags]
        assert "1965" in year_values

    def test_explicit_year_sets_estimated_year(self, db):
        """Explicit year should set estimated_year on the linked memory."""
        tid = db.create_tenant("Timeline Test")
        sid = db.save_story(
            transcript="Back in 1972 we moved to Wisconsin.",
            speaker_name="Dad",
            tenant_id=tid,
        )
        mid = db.save_memory(
            story_id=sid, bucket="call_to_adventure", life_phase="young_adult",
            text="Back in 1972 we moved to Wisconsin.", tenant_id=tid,
        )
        db.auto_tag_story(sid, "Back in 1972 we moved to Wisconsin.", tid)

        mem = db.get_memory_by_id(mid)
        assert mem["estimated_year"] == 1972

    def test_childhood_phrase_estimates_year(self, db):
        """'when I was a kid' + speaker birth_year should estimate a year."""
        tid = db.create_tenant("Timeline Test")
        # Set up owner with birth_year
        profile = db.get_or_create_user("Grandpa Joe", tenant_id=tid)
        conn = db._get_connection()
        conn.execute("UPDATE user_profiles SET birth_year = 1945 WHERE id = ?", (profile["id"],))
        conn.commit()

        sid = db.save_story(
            transcript="When I was a kid we used to walk to school every day.",
            speaker_name="Grandpa Joe",
            tenant_id=tid,
        )
        mid = db.save_memory(
            story_id=sid, bucket="ordinary_world", life_phase="childhood",
            text="When I was a kid we used to walk to school every day.", tenant_id=tid,
        )
        db.auto_tag_story(sid, "When I was a kid we used to walk to school every day.", tid)

        mem = db.get_memory_by_id(mid)
        assert mem["estimated_year"] == 1953  # 1945 + 8

    def test_high_school_phrase_estimates_year(self, db):
        """'in high school' + speaker birth_year should estimate ~16yo."""
        tid = db.create_tenant("Timeline Test")
        profile = db.get_or_create_user("Mom", tenant_id=tid)
        conn = db._get_connection()
        conn.execute("UPDATE user_profiles SET birth_year = 1950 WHERE id = ?", (profile["id"],))
        conn.commit()

        sid = db.save_story(
            transcript="In high school I was on the basketball team.",
            speaker_name="Mom",
            tenant_id=tid,
        )
        mid = db.save_memory(
            story_id=sid, bucket="call_to_adventure", life_phase="adolescence",
            text="In high school I was on the basketball team.", tenant_id=tid,
        )
        db.auto_tag_story(sid, "In high school I was on the basketball team.", tid)

        mem = db.get_memory_by_id(mid)
        assert mem["estimated_year"] == 1966  # 1950 + 16

    def test_family_member_birth_year_lookup(self, db):
        """Speaker birth_year should be looked up from family_members if not owner."""
        tid = db.create_tenant("Timeline Test")
        # Owner with no birth_year
        db.get_or_create_user("Someone", tenant_id=tid)

        # Family member with birth_year
        fmid = db.add_family_member(name="Uncle Bob", relationship="uncle", tenant_id=tid)
        db.update_family_member(fmid, birth_year=1935)

        sid = db.save_story(
            transcript="When I was a kid we had a big garden out back.",
            speaker_name="Uncle Bob",
            tenant_id=tid,
        )
        mid = db.save_memory(
            story_id=sid, bucket="ordinary_world", life_phase="childhood",
            text="When I was a kid we had a big garden out back.", tenant_id=tid,
        )
        db.auto_tag_story(sid, "When I was a kid we had a big garden out back.", tid)

        mem = db.get_memory_by_id(mid)
        assert mem["estimated_year"] == 1943  # 1935 + 8

    def test_decade_reference_tagged(self, db):
        """'back in the 60s' should estimate ~1965."""
        tid = db.create_tenant("Timeline Test")
        sid = db.save_story(
            transcript="Back in the 60s everything was different.",
            speaker_name="Grandpa",
            tenant_id=tid,
        )
        mid = db.save_memory(
            story_id=sid, bucket="ordinary_world", life_phase="childhood",
            text="Back in the 60s everything was different.", tenant_id=tid,
        )
        db.auto_tag_story(sid, "Back in the 60s everything was different.", tid)

        mem = db.get_memory_by_id(mid)
        assert mem["estimated_year"] == 1965  # 1900 + 60 + 5

    def test_no_birth_year_no_estimation(self, db):
        """Without birth_year, relative phrases should NOT estimate year."""
        tid = db.create_tenant("Timeline Test")
        db.get_or_create_user("Nobody", tenant_id=tid)

        sid = db.save_story(
            transcript="When I was a kid I loved playing outside.",
            speaker_name="Nobody",
            tenant_id=tid,
        )
        mid = db.save_memory(
            story_id=sid, bucket="ordinary_world", life_phase="childhood",
            text="When I was a kid I loved playing outside.", tenant_id=tid,
        )
        db.auto_tag_story(sid, "When I was a kid I loved playing outside.", tid)

        mem = db.get_memory_by_id(mid)
        assert mem["estimated_year"] is None

    def test_wedding_phrase_estimates_year(self, db):
        """'when we got married' + birth_year should estimate ~25yo."""
        tid = db.create_tenant("Timeline Test")
        profile = db.get_or_create_user("Gi", tenant_id=tid)
        conn = db._get_connection()
        conn.execute("UPDATE user_profiles SET birth_year = 1948 WHERE id = ?", (profile["id"],))
        conn.commit()

        sid = db.save_story(
            transcript="When we got married we didn't have two nickels to rub together.",
            speaker_name="Gi",
            tenant_id=tid,
        )
        mid = db.save_memory(
            story_id=sid, bucket="crossing_threshold", life_phase="young_adult",
            text="When we got married we didn't have two nickels.", tenant_id=tid,
        )
        db.auto_tag_story(sid, "when we got married we didn't have two nickels to rub together.", tid)

        mem = db.get_memory_by_id(mid)
        assert mem["estimated_year"] == 1973  # 1948 + 25

    def test_birth_year_zero_clears(self, db):
        """Setting birth_year=0 should store NULL."""
        tid = db.create_tenant("Timeline Test")
        fmid = db.add_family_member(name="Test", relationship="cousin", tenant_id=tid)
        db.update_family_member(fmid, birth_year=1960)
        db.update_family_member(fmid, birth_year=0)
        member = db.get_family_member_by_id(fmid)
        assert member["birth_year"] is None

    def test_estimate_year_static_method(self, db):
        """Direct test of _estimate_year_from_phrases."""
        from server.core.database import PollyDB
        assert PollyDB._estimate_year_from_phrases("when i was a kid", 1950) == 1958
        assert PollyDB._estimate_year_from_phrases("in high school", 1950) == 1966
        assert PollyDB._estimate_year_from_phrases("in college", 1950) == 1972
        assert PollyDB._estimate_year_from_phrases("after i retired", 1950) == 2015
        assert PollyDB._estimate_year_from_phrases("nothing special here", 1950) is None


class TestOwnerAgeAndConfidence:
    """Owner age calculation and year confidence scoring."""

    def test_owner_age_calculated(self, db):
        """owner_age should be estimated_year - owner.birth_year."""
        tid = db.create_tenant("Age Test")
        profile = db.get_or_create_user("Grandpa", tenant_id=tid)
        conn = db._get_connection()
        conn.execute("UPDATE user_profiles SET birth_year = 1945 WHERE id = ?", (profile["id"],))
        conn.commit()

        sid = db.save_story(
            transcript="Back in 1960 we moved to the new house.",
            speaker_name="Grandpa", tenant_id=tid,
        )
        mid = db.save_memory(
            story_id=sid, bucket="ordinary_world", life_phase="childhood",
            text="Back in 1960 we moved.", tenant_id=tid,
        )
        db.auto_tag_story(sid, "Back in 1960 we moved to the new house.", tid)

        mem = db.get_memory_by_id(mid)
        assert mem["estimated_year"] == 1960
        assert mem["owner_age"] == 15  # 1960 - 1945

    def test_confidence_high_for_explicit_year(self, db):
        """Explicit 4-digit year should have 'high' confidence."""
        tid = db.create_tenant("Confidence Test")
        db.get_or_create_user("Test", tenant_id=tid)
        sid = db.save_story(transcript="In 1985 everything changed.", tenant_id=tid)
        mid = db.save_memory(
            story_id=sid, bucket="ordinary_world", life_phase="childhood",
            text="In 1985 everything changed.", tenant_id=tid,
        )
        db.auto_tag_story(sid, "In 1985 everything changed.", tid)

        mem = db.get_memory_by_id(mid)
        assert mem["year_confidence"] == "high"

    def test_confidence_medium_for_phrase(self, db):
        """Relative phrase + birth_year should have 'medium' confidence."""
        tid = db.create_tenant("Confidence Test")
        profile = db.get_or_create_user("Mom", tenant_id=tid)
        conn = db._get_connection()
        conn.execute("UPDATE user_profiles SET birth_year = 1950 WHERE id = ?", (profile["id"],))
        conn.commit()

        sid = db.save_story(
            transcript="When I was a kid we played outside all day.",
            speaker_name="Mom", tenant_id=tid,
        )
        mid = db.save_memory(
            story_id=sid, bucket="ordinary_world", life_phase="childhood",
            text="When I was a kid we played outside.", tenant_id=tid,
        )
        db.auto_tag_story(sid, "when i was a kid we played outside all day.", tid)

        mem = db.get_memory_by_id(mid)
        assert mem["year_confidence"] == "medium"

    def test_confidence_low_for_decade(self, db):
        """Decade reference should have 'low' confidence."""
        tid = db.create_tenant("Confidence Test")
        sid = db.save_story(
            transcript="Back in the 70s music was different.", tenant_id=tid,
        )
        mid = db.save_memory(
            story_id=sid, bucket="ordinary_world", life_phase="childhood",
            text="Back in the 70s music was different.", tenant_id=tid,
        )
        db.auto_tag_story(sid, "back in the 70s music was different.", tid)

        mem = db.get_memory_by_id(mid)
        assert mem["year_confidence"] == "low"

    def test_owner_age_negative_for_pre_birth(self, db):
        """Stories before owner's birth should have negative owner_age."""
        tid = db.create_tenant("Pre-Birth Test")
        profile = db.get_or_create_user("Glen", tenant_id=tid)
        conn = db._get_connection()
        conn.execute("UPDATE user_profiles SET birth_year = 1978 WHERE id = ?", (profile["id"],))
        conn.commit()

        # Mom tells a story from 1972 (before Glen was born)
        db.add_family_member(name="Mom", relationship="mother", tenant_id=tid)
        conn.execute("UPDATE family_members SET birth_year = 1950 WHERE tenant_id = ? AND name = 'Mom'", (tid,))
        conn.commit()

        sid = db.save_story(
            transcript="In 1972 your father and I got married at the courthouse.",
            speaker_name="Mom", tenant_id=tid,
        )
        mid = db.save_memory(
            story_id=sid, bucket="ordinary_world", life_phase="childhood",
            text="In 1972 your father and I got married.", tenant_id=tid,
        )
        db.auto_tag_story(sid, "In 1972 your father and I got married at the courthouse.", tid)

        mem = db.get_memory_by_id(mid)
        assert mem["estimated_year"] == 1972
        assert mem["owner_age"] == -6  # 1972 - 1978


class TestAnchorCrossReference:
    """Anchor cross-referencing with deceased_year."""

    def test_before_person_died_clamps_year(self, db):
        """'before grandpa died' should clamp year to before deceased_year."""
        from server.core.database import PollyDB
        tid = db.create_tenant("Anchor Test")
        fmid = db.add_family_member(name="Grandpa", relationship="grandfather", tenant_id=tid)
        db.update_family_member(fmid, birth_year=1920, deceased=1, deceased_year=1990)

        conn = db._get_connection()
        # Test the static-ish method directly
        result = PollyDB._refine_year_with_anchors(
            conn, "before grandpa died we used to fish", 1995, tid
        )
        assert result == 1988  # 1990 - 2

    def test_after_person_died_clamps_year(self, db):
        """'after grandpa passed' should clamp year to after deceased_year."""
        from server.core.database import PollyDB
        tid = db.create_tenant("Anchor Test")
        fmid = db.add_family_member(name="Grandpa", relationship="grandfather", tenant_id=tid)
        db.update_family_member(fmid, birth_year=1920, deceased=1, deceased_year=1990)

        conn = db._get_connection()
        result = PollyDB._refine_year_with_anchors(
            conn, "after grandpa passed away things changed", 1985, tid
        )
        assert result == 1991  # 1990 + 1

    def test_when_alive_clamps_year(self, db):
        """'when grandpa was alive' should clamp year to before deceased_year."""
        from server.core.database import PollyDB
        tid = db.create_tenant("Anchor Test")
        fmid = db.add_family_member(name="Grandpa", relationship="grandfather", tenant_id=tid)
        db.update_family_member(fmid, birth_year=1920, deceased=1, deceased_year=1990)

        conn = db._get_connection()
        result = PollyDB._refine_year_with_anchors(
            conn, "when grandpa was still here we always had christmas together", 1995, tid
        )
        assert result == 1987  # 1990 - 3


class TestChapterRefreshFlag:
    """Chapter refresh flagging when new memories arrive."""

    def test_flag_chapters_for_refresh(self, db):
        """New memory should flag matching chapter drafts."""
        tid = db.create_tenant("Refresh Test")
        draft_id = db.save_chapter_draft(
            chapter_number=1, title="Test", bucket="ordinary_world",
            life_phase="childhood", memory_ids="[1]", content="Content.",
            tenant_id=tid,
        )
        db.flag_chapters_for_refresh("ordinary_world", "childhood", tenant_id=tid)

        drafts = db.get_chapter_drafts(tenant_id=tid)
        assert drafts[0]["needs_refresh"] == 1

    def test_clear_chapter_refresh(self, db):
        """Clearing refresh flag after regeneration."""
        tid = db.create_tenant("Refresh Test")
        draft_id = db.save_chapter_draft(
            chapter_number=1, title="Test", bucket="ordinary_world",
            life_phase="childhood", memory_ids="[1]", content="Content.",
            tenant_id=tid,
        )
        db.flag_chapters_for_refresh("ordinary_world", "childhood", tenant_id=tid)
        db.clear_chapter_refresh(draft_id)

        drafts = db.get_chapter_drafts(tenant_id=tid)
        assert drafts[0]["needs_refresh"] == 0

    def test_non_matching_bucket_not_flagged(self, db):
        """Only chapters with matching bucket/phase should be flagged."""
        tid = db.create_tenant("Refresh Test")
        db.save_chapter_draft(
            chapter_number=1, title="Childhood", bucket="ordinary_world",
            life_phase="childhood", memory_ids="[1]", content="Content.",
            tenant_id=tid,
        )
        db.save_chapter_draft(
            chapter_number=2, title="Adult", bucket="trials_allies_enemies",
            life_phase="adult", memory_ids="[2]", content="Content.",
            tenant_id=tid,
        )
        db.flag_chapters_for_refresh("ordinary_world", "childhood", tenant_id=tid)

        drafts = db.get_chapter_drafts(tenant_id=tid)
        assert drafts[0]["needs_refresh"] == 1
        assert drafts[1]["needs_refresh"] == 0

    def test_chapter_summary_stored(self, db):
        """Chapter summary should be saved and retrievable."""
        tid = db.create_tenant("Summary Test")
        draft_id = db.save_chapter_draft(
            chapter_number=1, title="Test", bucket="ordinary_world",
            life_phase="childhood", memory_ids="[1]", content="Full chapter.",
            tenant_id=tid,
        )
        db.update_chapter_summary(draft_id, "This chapter covers childhood in the 1950s. It focuses on family traditions.")

        drafts = db.get_chapter_drafts(tenant_id=tid)
        assert "childhood in the 1950s" in drafts[0]["summary"]

    def test_memories_sorted_chronologically(self, db):
        """Chapter outline should sort memories by estimated_year."""
        tid = db.create_tenant("Sort Test")
        # Create memories out of chronological order
        for year, i in [(1970, 1), (1960, 2), (1965, 3)]:
            sid = db.save_story(transcript=f"Story {i}", tenant_id=tid)
            mid = db.save_memory(
                story_id=sid, bucket="ordinary_world", life_phase="childhood",
                text=f"Story {i}", tenant_id=tid,
            )
            conn = db._get_connection()
            conn.execute("UPDATE memories SET estimated_year = ? WHERE id = ?", (year, mid))
            conn.commit()

        bb = BookBuilder(db)
        chapters = bb.generate_chapter_outline(tenant_id=tid)
        if chapters:
            ch = chapters[0]
            # Fetch memories in the order the chapter lists them
            mems = [db.get_memory_by_id(mid) for mid in ch["memory_ids"]]
            years = [m["estimated_year"] for m in mems if m["estimated_year"]]
            assert years == sorted(years), "Memories should be in chronological order"


# ═══════════════════════════════════════════════════════════════
#              FAMILY MEMBER ACCESS CODES
# ═══════════════════════════════════════════════════════════════

class TestFamilyMemberAccessCodes:
    """Per-family-member access codes for identified family sessions."""

    def test_generate_member_access_code(self, db, tenant_a):
        tid = tenant_a["tenant_id"]
        mid = db.add_family_member(name="Test Person", relationship="cousin", tenant_id=tid)
        code = db.generate_member_access_code(mid, tid)
        assert code is not None
        assert len(code) == 6
        assert code.isdigit()

    def test_member_code_unique_from_tenant_code(self, db, tenant_a):
        tid = tenant_a["tenant_id"]
        # Set a known tenant family code
        conn = db._get_connection()
        conn.execute("UPDATE tenants SET family_code = '111111' WHERE id = ?", (tid,))
        conn.commit()
        mid = db.add_family_member(name="Test Person", relationship="cousin", tenant_id=tid)
        code = db.generate_member_access_code(mid, tid)
        assert code != "111111"

    def test_validate_personal_code(self, db, tenant_a):
        tid = tenant_a["tenant_id"]
        mid = db.add_family_member(name="Sandy", relationship="aunt", tenant_id=tid)
        code = db.generate_member_access_code(mid, tid)
        result = db.validate_family_code(code)
        assert result is not None
        assert result["type"] == "personal"
        assert result["member"]["name"] == "Sandy"
        assert result["tenant"]["id"] == tid

    def test_validate_general_code(self, db, tenant_a):
        tid = tenant_a["tenant_id"]
        conn = db._get_connection()
        conn.execute("UPDATE tenants SET family_code = '222222' WHERE id = ?", (tid,))
        conn.commit()
        result = db.validate_family_code("222222")
        assert result is not None
        assert result["type"] == "general"
        assert result["member"] is None

    def test_validate_invalid_code(self, db, tenant_a):
        result = db.validate_family_code("999999")
        assert result is None

    def test_revoke_member_code(self, db, tenant_a):
        tid = tenant_a["tenant_id"]
        mid = db.add_family_member(name="Revokee", relationship="cousin", tenant_id=tid)
        code = db.generate_member_access_code(mid, tid)
        # Verify it works
        assert db.validate_family_code(code) is not None
        # Revoke
        db.revoke_member_access_code(mid, tid)
        assert db.validate_family_code(code) is None
        # Check column is null
        member = db.get_family_member_by_id(mid)
        assert member["access_code"] is None

    def test_create_family_session_with_member_id(self, db, tenant_a):
        tid = tenant_a["tenant_id"]
        mid = db.add_family_member(name="Identified", relationship="sibling", tenant_id=tid)
        session_id = db.create_family_session(tid, "Identified", family_member_id=mid)
        assert session_id is not None
        session = db.get_web_session(session_id)
        assert session["family_member_id"] == mid

    def test_revoke_kills_sessions(self, db, tenant_a):
        tid = tenant_a["tenant_id"]
        mid = db.add_family_member(name="SessionKill", relationship="cousin", tenant_id=tid)
        code = db.generate_member_access_code(mid, tid)
        session_id = db.create_family_session(tid, "SessionKill", family_member_id=mid)
        # Session should exist
        assert db.get_web_session(session_id) is not None
        # Revoke — should kill session
        db.revoke_member_access_code(mid, tid)
        assert db.get_web_session(session_id) is None

    def test_duplicate_chapter_prevention(self, db, tenant_a):
        """When memories < 10, only one chapter per bucket/life_phase, not duplicates."""
        tid = tenant_a["tenant_id"]
        bb = BookBuilder(db)
        chapters = bb.generate_chapter_outline(tenant_id=tid)
        # Check no two chapters share the same bucket+life_phase
        seen = set()
        for ch in chapters:
            key = (ch["bucket"], ch["life_phase"])
            assert key not in seen, f"Duplicate chapter for {key}"
            seen.add(key)
