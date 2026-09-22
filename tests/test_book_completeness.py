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


def test_written_chapter_keeps_its_memories(db):
    """Sticky: a draft's memories stay in its chapter even if their bucket
    no longer matches — the prose tells them there."""
    bb = BookBuilder(db)
    mids = [add(db, f"Childhood {i}", "ordinary_world", "childhood")[1] for i in range(3)]
    db.save_chapter_draft(chapter_number=1, title="The Hard Years",
                          bucket="trials_allies_enemies", life_phase="adult",
                          memory_ids=json.dumps(mids), content="Hard prose.", tenant_id=TID)
    chapters = bb.generate_chapter_outline(tenant_id=TID)
    bb.match_drafts(chapters, db.get_chapter_drafts(tenant_id=TID))
    assert len(chapters) == 1 and chapters[0]["title"] == "The Hard Years"
    assert chapters[0]["draft_stale"] is False and chapters[0]["uncovered_ids"] == []


def test_adding_a_story_does_not_reshuffle_written_chapters(db):
    bb = BookBuilder(db)
    kids = [add(db, f"Childhood {i}", "ordinary_world", "childhood", year=1985 + i)[1] for i in range(10)]
    adult = [add(db, f"Adult {i}", "transformation", "adult", year=2010 + i)[1] for i in range(5)]
    for ch in bb.generate_chapter_outline(tenant_id=TID):
        db.save_chapter_draft(chapter_number=ch["chapter_number"], title=ch["title"],
                              bucket=ch["bucket"], life_phase=ch["life_phase"],
                              memory_ids=json.dumps(ch["memory_ids"]), content="Prose.", tenant_id=TID)
    # An OLDER childhood story arrives — it used to shift every chunk after it
    add(db, "The earliest memory of all", "ordinary_world", "childhood", year=1980)
    chapters = bb.generate_chapter_outline(tenant_id=TID)
    bb.match_drafts(chapters, db.get_chapter_drafts(tenant_id=TID))
    # Only the chapter the newcomer joined changes; everything else stays put
    stale = [c for c in chapters if c["draft_stale"]]
    assert len(stale) == 1 and set(kids) < set(stale[0]["memory_ids"])
    assert any(set(c["memory_ids"]) == set(adult) and not c["draft_stale"] for c in chapters)


def test_full_chapters_overflow_into_a_new_one(db):
    bb = BookBuilder(db)
    add(db, "Seed kid story", "ordinary_world", "childhood")
    add(db, "Seed kid story 2", "ordinary_world", "childhood")
    ch = bb.generate_chapter_outline(tenant_id=TID)[0]
    full = ch["memory_ids"] + [add(db, f"Kid {i}", "ordinary_world", "childhood")[1] for i in range(11)]
    db.save_chapter_draft(chapter_number=1, title="Where It All Started", bucket="ordinary_world",
                          life_phase="childhood", memory_ids=json.dumps(full), content="P.", tenant_id=TID)
    lone = add(db, "One more kid story", "ordinary_world", "childhood")[1]
    chapters = bb.generate_chapter_outline(tenant_id=TID)
    assert len(chapters) == 2
    assert chapters[1]["memory_ids"] == [lone] and chapters[1]["title"].endswith("(more)")


def test_chapters_read_in_life_order(db):
    bb = BookBuilder(db)
    for i in range(2):
        add(db, f"Wisdom {i}", "return_with_knowledge", "reflection")
        add(db, f"Kid {i}", "ordinary_world", "childhood")
        add(db, f"Twenties {i}", "call_to_adventure", "young_adult")
    phases = [c["life_phase"] for c in bb.generate_chapter_outline(tenant_id=TID)]
    assert phases == ["childhood", "young_adult", "reflection"]


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


# ── Background refresh (fake AI — no network, no cost) ──

class _FakeAI:
    """Stands in for followup_gen: writes prose that tells every memory."""
    available = True

    def __init__(self):
        self.calls = 0
        outer = self

        class _Completions:
            def create(self, model, messages, **kw):
                outer.calls += 1
                prompt = messages[-1]["content"]
                if kw.get("response_format"):            # coverage check
                    out = '{"missing": []}'
                elif "title of 2 to 5 words" in prompt:
                    out = "Summers at the Lake"
                elif prompt.startswith("Summarize"):
                    out = "Two sentences."
                else:                                     # the chapter itself
                    out = "\n\n".join(re.findall(r"\): (.*)", prompt)) or "Prose."
                msg = type("M", (), {"content": out})
                return type("R", (), {"choices": [type("C", (), {"message": msg})]})

        self._client = type("Cl", (), {"chat": type("Ch", (), {"completions": _Completions()})})()


def _written_book(db):
    bb = BookBuilder(db, followup_generator=_FakeAI())
    for i in range(3):
        add(db, f"Lake story {i}", "ordinary_world", "adult")
    for ch in bb.generate_chapter_outline(tenant_id=TID):
        db.save_chapter_draft(chapter_number=ch["chapter_number"], title=ch["title"],
                              bucket=ch["bucket"], life_phase=ch["life_phase"],
                              memory_ids=json.dumps(ch["memory_ids"]), content="Old prose.", tenant_id=TID)
    return bb


def _age_everything(db):
    conn = db._get_connection()
    for t in ("stories", "memories"):
        conn.execute(f"UPDATE {t} SET created_at = datetime('now', '-2 hours')")
    conn.commit()
    conn.close()


def test_refresher_rewrites_stale_chapter_and_keeps_old_version(db):
    import asyncio
    from core.book_refresh import ChapterRefresher
    bb = _written_book(db)
    add(db, "A brand new lake story", "ordinary_world", "adult")
    _age_everything(db)
    r = ChapterRefresher(db, bb)
    assert r._quiet(TID)
    assert asyncio.run(r.refresh_tenant(TID)) == 1
    d = db.get_chapter_drafts(tenant_id=TID)[0]
    assert d["previous_content"] == "Old prose."
    assert "A brand new lake story" in d["content"]
    assert d["title"] == "Summers at the Lake"   # generic "(more)" title replaced
    assert r.stale_chapters(TID)[1] == []        # fresh now


def test_refresher_never_rewrites_hand_edited_chapter(db):
    import asyncio
    from core.book_refresh import ChapterRefresher
    bb = _written_book(db)
    conn = db._get_connection()
    conn.execute("UPDATE chapter_drafts SET hand_edited = 1")
    conn.commit()
    conn.close()
    add(db, "Another lake story", "ordinary_world", "adult")
    _age_everything(db)
    assert asyncio.run(ChapterRefresher(db, bb).refresh_tenant(TID)) == 0
    assert db.get_chapter_drafts(tenant_id=TID)[0]["content"] == "Old prose."


def test_refresher_waits_while_stories_are_still_coming_in(db):
    from core.book_refresh import ChapterRefresher
    bb = _written_book(db)
    add(db, "Just now", "ordinary_world", "adult")
    assert ChapterRefresher(db, bb)._quiet(TID) is False


def test_writing_chapters_never_disturbs_other_chapters(db):
    """The outline is a fixed point: anchoring (writing) chapters one at a
    time leaves every other chapter's stories where they were."""
    bb = BookBuilder(db)
    for i in range(3):
        add(db, f"Kid {i}", "ordinary_world", "childhood")
        add(db, f"Twenties {i}", "call_to_adventure", "young_adult")
    add(db, "Lone twenties plain day", "ordinary_world", "young_adult")   # straggler
    add(db, "Lone twenties hard time", "trials_allies_enemies", "young_adult")
    add(db, "Lone elder wisdom", "return_with_knowledge", "elder")
    before = [sorted(c["memory_ids"]) for c in bb.generate_chapter_outline(tenant_id=TID)]
    for ch in list(bb.generate_chapter_outline(tenant_id=TID))[::-1]:   # write in any order
        db.save_chapter_draft(chapter_number=ch["chapter_number"], title=f"T{ch['chapter_number']}",
                              bucket=ch["bucket"], life_phase=ch["life_phase"],
                              memory_ids=json.dumps(ch["memory_ids"]), content="P.", tenant_id=TID)
        after = [sorted(c["memory_ids"]) for c in bb.generate_chapter_outline(tenant_id=TID)]
        assert after == before


def test_resorted_story_moves_and_both_chapters_refresh(db):
    import asyncio
    bb = BookBuilder(db, followup_generator=_FakeAI())
    kids = [add(db, f"Kid {i}", "ordinary_world", "childhood")[1] for i in range(3)]
    dad = [add(db, f"Dad story {i}", "ordinary_world", "adult")[1] for i in range(3)]
    outline = bb.generate_chapter_outline(tenant_id=TID)
    for ch in outline:
        asyncio.run(bb.write_chapter(ch, TID, outline))
    # the sorter corrects a story: it was the parent's adult life, not childhood
    conn = db._get_connection()
    conn.execute("UPDATE memories SET life_phase = 'adult' WHERE id = ?", (kids[0],))
    conn.commit()
    conn.close()
    chapters = bb.generate_chapter_outline(tenant_id=TID)
    bb.match_drafts(chapters, db.get_chapter_drafts(tenant_id=TID))
    child = next(c for c in chapters if c["life_phase"] == "childhood")
    adult = next(c for c in chapters if c["life_phase"] == "adult")
    assert kids[0] not in child["memory_ids"] and kids[0] in adult["memory_ids"]
    assert child["draft_stale"] and adult["draft_stale"]
    assert set(kids[1:]) <= set(child["memory_ids"]) and set(dad) <= set(adult["memory_ids"])


def test_family_tree_reaches_the_sorter(db):
    import api.web as web
    conn = db._get_connection()
    conn.execute("INSERT INTO user_profiles (tenant_id, name, birth_year) VALUES (?, 'Glen', 1978)", (TID,))
    conn.execute("INSERT INTO family_members (name, name_normalized, relationship, birth_year, tenant_id) "
                 "VALUES ('Brooklyn', 'brooklyn', 'daughter', 2019, ?), ('Pal', 'pal', 'friend', 1980, ?)",
                 (TID, TID))
    conn.commit()
    conn.close()
    ctx = web._family_context(db, TID)
    assert "belongs to Glen, born 1978" in ctx and "Brooklyn: daughter, born 2019" in ctx
    assert "Pal" not in ctx   # friends aren't family context
