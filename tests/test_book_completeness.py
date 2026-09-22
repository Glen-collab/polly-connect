"""
The book must contain every story. These tests pin the rules that used to
drop stories silently:
  - only 'verified' memories reached the outline (verify lives on stories)
  - a lone memory in its bucket/phase was discarded
  - viewing the outline rewrote buckets from any year found in the text
  - drafts were matched to chapters by number, which shifts
  - the PDF skipped chapters with 2-4 memories and no draft
"""
import io
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from core.database import PollyDB
from core.book_builder import BookBuilder

TID = 1


@pytest.fixture
def db(tmp_path):
    return PollyDB(str(tmp_path / "book.db"))


def add(db, text, bucket, phase, verified=True, in_book=1, year=None, audio=None):
    """verified = the owner's ✔ on the STORY (what puts it in a chapter)."""
    sid = db.save_story(transcript=text, source="web_typed", tenant_id=TID, audio_s3_key=audio)
    conn = db._get_connection()
    conn.execute("UPDATE stories SET verified = ? WHERE id = ?", (int(verified), sid))
    conn.commit()
    conn.close()
    mid = db.save_memory(story_id=sid, bucket=bucket, life_phase=phase,
                         text=text, tenant_id=TID)
    conn = db._get_connection()
    # memories.verification_status stays 'unverified' on purpose — the web ✔
    # never set it, and the book must not depend on it.
    conn.execute("UPDATE memories SET include_in_book = ?, estimated_year = ? WHERE id = ?",
                 (in_book, year, mid))
    conn.commit()
    return sid, mid


def placed(chapters):
    return [m for ch in chapters for m in ch["memory_ids"]]


def test_story_checkmark_puts_it_in_a_chapter(db):
    mids = [add(db, f"Farm chores story {i}", "ordinary_world", "childhood")[1] for i in range(6)]
    ids = placed(BookBuilder(db).generate_chapter_outline(tenant_id=TID))
    assert sorted(ids) == sorted(mids)


def test_every_memory_placed_exactly_once_including_stragglers(db):
    mids = []
    for i in range(11):  # 11 -> a chunk of 10 plus a straggler of 1
        mids.append(add(db, f"Adult story {i}", "ordinary_world", "adult")[1])
    mids.append(add(db, "The one big decision", "crossing_threshold", "young_adult")[1])
    mids.append(add(db, "A lone odd one", "call_to_adventure", "elder")[1])
    ids = placed(BookBuilder(db).generate_chapter_outline(tenant_id=TID))
    assert len(ids) == len(set(ids)), "a memory is in two chapters"
    assert set(ids) == set(mids), f"dropped: {set(mids) - set(ids)}"


def test_book_toggle_is_the_only_exclusion(db):
    keep = add(db, "Keep me", "ordinary_world", "childhood")[1]
    drop = add(db, "Leave me out", "ordinary_world", "childhood", in_book=0)[1]
    ids = placed(BookBuilder(db).generate_chapter_outline(tenant_id=TID))
    assert keep in ids and drop not in ids


def test_viewing_the_outline_does_not_rewrite_buckets(db):
    conn = db._get_connection()
    conn.execute("INSERT INTO user_profiles (tenant_id, name, birth_year) VALUES (?, 'Test', 1978)", (TID,))
    conn.commit()
    _, mid = add(db, "Barn chores as a boy, and here we are in 2026 telling it", "ordinary_world", "childhood")
    BookBuilder(db).generate_chapter_outline(tenant_id=TID)
    row = db._get_connection().execute(
        "SELECT bucket, life_phase, estimated_year FROM memories WHERE id = ?", (mid,)).fetchone()
    assert row == ("ordinary_world", "childhood", None)


def test_drafts_match_by_content_and_new_stories_are_uncovered(db):
    bb = BookBuilder(db)
    old = [add(db, f"Childhood {i}", "ordinary_world", "childhood")[1] for i in range(3)]
    # Draft saved under the WRONG chapter number, as happens after renumbering
    db.save_chapter_draft(chapter_number=7, title="Where It All Started",
                          bucket="ordinary_world", life_phase="childhood",
                          memory_ids=json.dumps(old), content="Prose.", tenant_id=TID)
    new = add(db, "Childhood added later", "ordinary_world", "childhood")[1]
    chapters = bb.generate_chapter_outline(tenant_id=TID)
    bb.match_drafts(chapters, db.get_chapter_drafts(tenant_id=TID))
    ch = next(c for c in chapters if new in c["memory_ids"])
    assert ch["draft"] and ch["draft"]["title"] == "Where It All Started"
    assert ch["draft_stale"] is True
    assert ch["uncovered_ids"] == [new]


def test_draft_from_another_theme_is_not_used(db):
    bb = BookBuilder(db)
    mids = [add(db, f"Childhood {i}", "ordinary_world", "childhood")[1] for i in range(3)]
    db.save_chapter_draft(chapter_number=1, title="The Hard Years",
                          bucket="trials_allies_enemies", life_phase="adult",
                          memory_ids=json.dumps(mids), content="Hard prose.", tenant_id=TID)
    chapters = bb.generate_chapter_outline(tenant_id=TID)
    bb.match_drafts(chapters, db.get_chapter_drafts(tenant_id=TID))
    assert all(c["draft"] is None for c in chapters)
    assert sorted(m for c in chapters for m in c["uncovered_ids"]) == sorted(mids)


def test_ai_skipped_memories_print_verbatim(db):
    bb = BookBuilder(db)
    mids = [add(db, f"Childhood {i}", "ordinary_world", "childhood")[1] for i in range(3)]
    db.save_chapter_draft(chapter_number=1, title="Where It All Started",
                          bucket="ordinary_world", life_phase="childhood",
                          memory_ids=json.dumps(mids), content="Prose.", tenant_id=TID,
                          missing_memory_ids=json.dumps([mids[1]]))
    chapters = bb.generate_chapter_outline(tenant_id=TID)
    bb.match_drafts(chapters, db.get_chapter_drafts(tenant_id=TID))
    assert chapters[0]["uncovered_ids"] == [mids[1]]
    assert chapters[0]["draft_stale"] is False


def test_coverage_accounts_for_every_story(db):
    add(db, "In the book story", "ordinary_world", "childhood")
    add(db, "Taken out on purpose", "ordinary_world", "childhood", in_book=0)
    orphan = db.save_story(transcript="A verified story that never got a memory row", tenant_id=TID)
    conn = db._get_connection()
    conn.execute("UPDATE stories SET verified = 1 WHERE id = ?", (orphan,))
    conn.commit()
    conn.close()
    unchecked = db.save_story(transcript="Unverified, never sorted — kept in the appendix", tenant_id=TID)
    cov = BookBuilder(db).book_coverage(TID)
    states = {s["story_id"]: s["state"] for s in cov["stories"]}
    assert cov["total"] == 4 and cov["in_book"] == 2 and cov["appendix"] == 1
    assert states[orphan] == "no_memory" and states[unchecked] == "in_book"
    assert sorted(states.values()) == ["excluded", "in_book", "in_book", "no_memory"]


def test_pdf_prints_every_memory(db):
    pytest.importorskip("reportlab")
    pypdf = pytest.importorskip("pypdf")
    from core.book_pdf import LegacyBookPDF
    texts = [f"Unique memory number {i} about the red tractor" for i in range(4)]
    for t in texts[:2]:
        add(db, t, "ordinary_world", "childhood")       # 2-memory chapter, no draft
    add(db, texts[2], "transformation", "midlife")      # lone straggler
    add(db, texts[3], "call_to_adventure", "elder")     # lone, no matching chapter
    pdf = LegacyBookPDF(db, BookBuilder(db), tenant_id=TID).generate(include_qr_codes=False)
    text = " ".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    flat = re.sub(r"\s+", " ", text)
    for t in texts:
        assert t in flat, f"missing from PDF: {t}"


def test_audio_only_recording_is_in_the_book_as_a_qr(db):
    sid = db.save_story(transcript="(no transcription — audio saved)",
                        audio_s3_key="web_kids.wav", source="web_recording", tenant_id=TID)
    cov = BookBuilder(db).book_coverage(TID)
    entry = next(s for s in cov["stories"] if s["story_id"] == sid)
    assert entry["state"] == "in_book"
    assert entry["chapter"].startswith("Voice Recordings")


def test_audio_only_qr_label_uses_title_then_date():
    from core.book_pdf import _qr_label
    base = {"transcript": "(no transcription — audio saved)", "created_at": "2025-12-25 08:01:00"}
    assert _qr_label(base, 60) == "Voice recording, Dec 25, 2025"
    assert _qr_label({**base, "question_text": "Christmas morning chaos"}, 60) == "Christmas morning chaos"


def test_book_toggle_removes_the_qr_too(db):
    pytest.importorskip("reportlab")
    from core.book_pdf import LegacyBookPDF
    keep, _ = add(db, "Keep this story please", "ordinary_world", "childhood")
    drop, dmid = add(db, "Drop this story please", "ordinary_world", "childhood", in_book=0)
    conn = db._get_connection()
    conn.execute("UPDATE stories SET audio_s3_key = 'a' || id || '.wav' WHERE id IN (?, ?)", (keep, drop))
    conn.commit()
    pdf = LegacyBookPDF(db, BookBuilder(db), tenant_id=TID)
    orphans = pdf._get_orphan_audio([], set(), set())
    assert [o["audio_key"] for o in orphans] == [f"a{keep}.wav"]


def test_unverified_story_goes_to_appendix_not_a_chapter(db):
    bb = BookBuilder(db)
    ok = add(db, "Checked and correct", "ordinary_world", "childhood")[1]
    sid, bad = add(db, "Garbled transcript nobody checked", "ordinary_world", "childhood",
                   verified=False, audio="web_x.wav")
    ids = placed(bb.generate_chapter_outline(tenant_id=TID))
    assert ok in ids and bad not in ids
    assert [s["id"] for s in bb.appendix_stories(TID)] == [sid]
    entry = next(e for e in bb.book_coverage(TID)["stories"] if e["story_id"] == sid)
    assert entry["state"] == "in_book" and entry["chapter"].startswith("Appendix")


def test_appendix_prints_qr_label_not_the_unchecked_text(db):
    pytest.importorskip("reportlab")
    pypdf = pytest.importorskip("pypdf")
    from core.book_pdf import LegacyBookPDF
    add(db, "A verified story in its chapter", "ordinary_world", "childhood")
    sid, _ = add(db, "Garbled words that were never checked", "ordinary_world", "childhood",
                 verified=False, audio="web_y.wav")
    conn = db._get_connection()
    conn.execute("UPDATE stories SET question_text = 'Christmas morning chaos' WHERE id = ?", (sid,))
    conn.commit()
    conn.close()
    pdf = LegacyBookPDF(db, BookBuilder(db), tenant_id=TID).generate()
    text = re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf)).pages))
    assert "Appendix" in text and "Christmas morning chaos" in text
    assert "Garbled words that were never checked" not in text


def test_book_toggle_beats_the_appendix(db):
    bb = BookBuilder(db)
    add(db, "Unverified and taken out", "ordinary_world", "childhood", verified=False, in_book=0)
    assert bb.appendix_stories(TID) == []
