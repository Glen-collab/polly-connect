"""
Keeps every family's written book current as stories keep coming in.

When a written chapter gains (or loses) stories, it goes stale: until it is
rewritten, the new stories print word-for-word after the chapter, so nothing
is ever missing. This loop rewrites stale chapters in the background, once
the family has stopped adding stories for a while (a burst of five stories
costs one rewrite, not five).

Rules:
  - only chapters that already have a draft are rewritten — a family starts
    their book themselves (that is where the Buy-the-Book gate lives)
  - a chapter the owner edited by hand is never rewritten automatically
  - the tenant must still have book access (book_export)
  - a hard cap on chapters per tenant per pass bounds AI spend
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

CHECK_EVERY_S = 15 * 60       # how often to look for stale chapters
QUIET_MINUTES = 30            # wait this long after the last story change
MAX_PER_TENANT_PER_PASS = 5   # AI spend bound per family per pass


class ChapterRefresher:
    def __init__(self, db, book_builder):
        self.db = db
        self.book_builder = book_builder
        self._task = None
        self._busy = set()   # tenants being rewritten right now

    async def start(self):
        if not self.book_builder._ai_available:
            logger.info("Chapter refresher off (no AI key)")
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("Chapter refresher started")

    async def stop(self):
        if self._task:
            self._task.cancel()

    async def _loop(self):
        while True:
            await asyncio.sleep(CHECK_EVERY_S)
            try:
                for tid in self._tenants_with_drafts():
                    if self._quiet(tid):
                        await self.refresh_tenant(tid)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Chapter refresher pass failed: {e}")

    def stale_chapters(self, tenant_id: int):
        """(outline, written chapters whose stories changed, not hand-edited)."""
        outline = self.book_builder.generate_chapter_outline(tenant_id=tenant_id)
        self.book_builder.match_drafts(outline, self.db.get_chapter_drafts(tenant_id=tenant_id))
        return outline, [ch for ch in outline
                         if ch["draft"] and ch["draft_stale"] and not ch["draft"].get("hand_edited")]

    async def refresh_tenant(self, tenant_id: int, limit: int = MAX_PER_TENANT_PER_PASS) -> int:
        """Rewrite up to `limit` stale chapters, in book order. Returns count."""
        from core.subscription import check_feature
        if tenant_id in self._busy or not check_feature(self.db, tenant_id, "book_export"):
            return 0
        self._busy.add(tenant_id)
        done = 0
        try:
            outline, stale = self.stale_chapters(tenant_id)
            for ch in stale[:limit]:
                if await self.book_builder.write_chapter(ch, tenant_id, outline):
                    done += 1
                    # later chapters' continuity reads this one's new summary
                    outline, _ = self.stale_chapters(tenant_id)
            if done:
                logger.info(f"Refreshed {done} chapter(s) for tenant {tenant_id}")
        finally:
            self._busy.discard(tenant_id)
        return done

    def _tenants_with_drafts(self) -> list:
        conn = self.db._get_connection()
        try:
            return [r[0] for r in conn.execute(
                "SELECT DISTINCT tenant_id FROM chapter_drafts WHERE tenant_id IS NOT NULL")]
        finally:
            if not self.db._conn:
                conn.close()

    def _quiet(self, tenant_id: int) -> bool:
        """No story added, verified or sorted in the last QUIET_MINUTES."""
        conn = self.db._get_connection()
        try:
            row = conn.execute("""
                SELECT MAX(t) >= datetime('now', ?) FROM (
                    SELECT MAX(created_at) AS t FROM stories WHERE tenant_id = ?
                    UNION ALL SELECT MAX(verified_at) FROM stories WHERE tenant_id = ?
                    UNION ALL SELECT MAX(created_at) FROM memories WHERE tenant_id = ?)
            """, (f"-{QUIET_MINUTES} minutes", tenant_id, tenant_id, tenant_id)).fetchone()
            return not row or not row[0]
        finally:
            if not self.db._conn:
                conn.close()
