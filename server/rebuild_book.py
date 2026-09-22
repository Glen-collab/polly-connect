"""
One-shot: rebuild one family's book from scratch, correctly.

For books whose drafts were written while the old outline was dropping
stories and rewriting buckets. Steps:
  1. archive the family's current drafts (chapter_drafts_archive) — nothing lost
  2. re-sort every story with the question-aware AI classifier
     (years the owner typed in are kept)
  3. clear the drafts and write every chapter in book order through
     BookBuilder.write_chapter — the same path the Regenerate button and the
     background refresher use (coverage check, titles, summaries)
  4. print the coverage report

Run from /opt/polly-connect/server:
    set -a; . ../.env; set +a
    POLLY_DB_PATH=/opt/polly-connect/polly.db python3.11 rebuild_book.py --tenant 1
Flags: --skip-classify (keep current placements), --classify-only,
       --recheck (re-audit written chapters, rewrite only real gaps),
       --refresh (keep chapters; re-sort, then rewrite only chapters that changed)
"""
import argparse
import asyncio
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.web import _gpt_classify_story, _apply_gpt_classification, _family_context
from core.book_builder import BookBuilder
from core.database import PollyDB
from core.followup_generator import FollowupGenerator


def archive_drafts(conn, tid):
    conn.execute("CREATE TABLE IF NOT EXISTS chapter_drafts_archive AS "
                 "SELECT *, CURRENT_TIMESTAMP AS archived_at FROM chapter_drafts WHERE 0")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(chapter_drafts)")]
    arch = {r[1] for r in conn.execute("PRAGMA table_info(chapter_drafts_archive)")}
    for c in cols:   # drafts may have gained columns since the archive was made
        if c not in arch:
            conn.execute(f"ALTER TABLE chapter_drafts_archive ADD COLUMN {c}")
    n = conn.execute(f"INSERT INTO chapter_drafts_archive ({', '.join(cols)}, archived_at) "
                     f"SELECT {', '.join(cols)}, CURRENT_TIMESTAMP FROM chapter_drafts "
                     f"WHERE tenant_id = ?", (tid,)).rowcount
    conn.commit()
    return n


def snapshot_placements(bb, db, conn, tid):
    """Record where each written chapter's stories sit now, so a re-sort
    that changes a story's placement moves it (drafts from before
    placements were tracked would otherwise hold on to every story)."""
    n = 0
    for d in db.get_chapter_drafts(tenant_id=tid):
        if not d.get("placements"):
            ids = json.loads(d.get("memory_ids") or "[]")
            conn.execute("UPDATE chapter_drafts SET placements = ? WHERE id = ?",
                         (json.dumps(bb.placements_of(ids, tid)), d["id"]))
            n += 1
    conn.commit()
    return n


def reclassify(db, conn, tid):
    family = _family_context(db, tid)
    rows = conn.execute("""
        SELECT m.id, m.story_id, m.bucket, m.life_phase, m.speaker,
               COALESCE(NULLIF(TRIM(s.corrected_transcript), ''), s.transcript) AS text,
               s.question_text, u.birth_year
        FROM memories m JOIN stories s ON s.id = m.story_id
        LEFT JOIN user_profiles u ON u.tenant_id = m.tenant_id
        WHERE m.tenant_id = ? ORDER BY m.id
    """, (tid,)).fetchall()
    changed = 0
    for r in rows:
        text = (r["text"] or "").strip()
        if len(text) < 10 or text.startswith("(no transcription"):
            continue
        try:
            parsed = _gpt_classify_story(text, birth_year=r["birth_year"],
                                         question=r["question_text"], family=family,
                                         speaker=r["speaker"])
            _apply_gpt_classification(db, r["story_id"], tid, parsed,
                                      fallback_text=text, speaker=r["speaker"])
            old, new = f"{r['bucket']}/{r['life_phase']}", f"{parsed.get('bucket')}/{parsed.get('life_phase')}"
            if old != new:
                changed += 1
                print(f"  m{r['id']:<4} {old:36} -> {new:36} {text[:50]!r}")
        except Exception as e:
            print(f"  m{r['id']}: ERROR {e}")
        time.sleep(0.2)
    print(f"Re-sorted {len(rows)} memories; {changed} moved.")


async def write_all(bb, db, tid):
    written = 0
    while True:
        outline = bb.generate_chapter_outline(tenant_id=tid)
        bb.match_drafts(outline, db.get_chapter_drafts(tenant_id=tid))
        todo = [c for c in outline if not c["draft"] or c["draft_stale"]]
        if not todo:
            return written
        ch = todo[0]
        t0 = time.time()
        if not await bb.write_chapter(ch, tid, outline):
            print(f"  FAILED: {ch['title']} — stopping")
            return written
        written += 1
        miss = ch.get("missing_memory_ids") or []
        print(f"  {ch['chapter_number']:>2}. {ch['title']:<36} {ch['memory_count']:>2} stories"
              f"{f', {len(miss)} printed word-for-word' if miss else ''}  ({time.time() - t0:.0f}s)")
        if written > 60:
            print("  safety stop")
            return written


async def recheck_all(bb, db, conn, tid):
    """Strip model-written headings and re-audit every chapter with the
    evidence-based checker; rewrite only chapters with real gaps."""
    from core.book_builder import strip_heading
    rewrite = 0
    for d in db.get_chapter_drafts(tenant_id=tid):
        missing = await bb.recheck_coverage(d, tid)
        conn.execute("UPDATE chapter_drafts SET content = ?, missing_memory_ids = ? WHERE id = ?",
                     (strip_heading(d["content"]), json.dumps(missing), d["id"]))
        conn.commit()
        print(f"  {d['title']:<36} {len(json.loads(d['memory_ids'])):>2} stories, "
              f"was {len(json.loads(d.get('missing_memory_ids') or '[]'))} missing, now {len(missing)}")
        rewrite += bool(missing)
    if rewrite:
        print(f"Rewriting {rewrite} chapter(s) with real gaps:")
        outline = bb.generate_chapter_outline(tenant_id=tid)
        bb.match_drafts(outline, db.get_chapter_drafts(tenant_id=tid))
        for ch in outline:
            if ch["draft"] and json.loads(ch["draft"].get("missing_memory_ids") or "[]"):
                await bb.write_chapter(ch, tid, outline)
                print(f"  {ch['title']:<36} now {len(ch.get('missing_memory_ids') or [])} missing")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", type=int, required=True)
    ap.add_argument("--skip-classify", action="store_true")
    ap.add_argument("--classify-only", action="store_true")
    ap.add_argument("--refresh", action="store_true",
                    help="re-sort (unless --skip-classify), then rewrite only chapters that changed")
    ap.add_argument("--recheck", action="store_true",
                    help="re-audit existing chapters; rewrite only ones with real gaps")
    a = ap.parse_args()

    db_path = os.getenv("POLLY_DB_PATH") or os.path.join(os.path.dirname(__file__), "..", "polly.db")
    db = PollyDB(db_path)
    fg = FollowupGenerator()
    if not fg.available:
        sys.exit("OPENAI_API_KEY not set")
    bb = BookBuilder(db, followup_generator=fg)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    if a.recheck:
        asyncio.run(recheck_all(bb, db, conn, a.tenant))
        cov = bb.book_coverage(a.tenant)
        print(f"Coverage: {cov['in_book']} of {cov['total']} ({cov['appendix']} in the appendix)")
        return

    if a.refresh or a.classify_only:
        print(f"Snapshotted placements for {snapshot_placements(bb, db, conn, a.tenant)} chapter(s)")
    if a.refresh:
        if not a.skip_classify:
            reclassify(db, conn, a.tenant)
        n = asyncio.run(write_all(bb, db, a.tenant))
        cov = bb.book_coverage(a.tenant)
        print(f"Rewrote {n} chapter(s). Coverage: {cov['in_book']} of {cov['total']} "
              f"({cov['appendix']} in the appendix)")
        return
    if not a.classify_only:
        print(f"Archived {archive_drafts(conn, a.tenant)} draft(s) to chapter_drafts_archive")
    if not a.skip_classify:
        reclassify(db, conn, a.tenant)
    if a.classify_only:
        return
    conn.execute("DELETE FROM chapter_drafts WHERE tenant_id = ?", (a.tenant,))
    conn.commit()
    n = asyncio.run(write_all(bb, db, a.tenant))
    cov = bb.book_coverage(a.tenant)
    print(f"\nWrote {n} chapters. Coverage: {cov['in_book']} of {cov['total']} stories in the book "
          f"({cov['appendix']} in the appendix).")
    for s in cov["stories"]:
        if s["state"] != "in_book":
            print(f"  not in book: story {s['story_id']} — {s['reason']}")


if __name__ == "__main__":
    main()
