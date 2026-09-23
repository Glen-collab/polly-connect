"""
Question engine for Polly Connect.
Manages guided question sequences — 5 base questions/week,
tracks answered vs pending per user.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class QuestionEngine:
    """
    Manages question sessions:
    - Picks the current week's questions from data loader
    - Tracks which have been answered
    - Provides next unanswered question
    - Manages question → record answer → next question flow
    """

    def __init__(self, db, data_loader):
        self.db = db
        self.data = data_loader

    def get_current_week(self) -> int:
        """Get current week number (1-52)."""
        return datetime.now().isocalendar()[1]

    def get_week_questions(self, week: int = None) -> List[Dict]:
        """Get questions for a specific week."""
        if week is None:
            week = self.get_current_week()

        for week_block in self.data.questions:
            if week_block.get("week") == week:
                return week_block.get("questions", [])

        # Wrap around if week > available weeks
        total_weeks = len(self.data.questions)
        if total_weeks > 0:
            wrapped = ((week - 1) % total_weeks)
            return self.data.questions[wrapped].get("questions", [])
        return []

    def get_next_question(self, user_id: int = None, tenant_id: int = None) -> Optional[Dict]:
        """Get the next unanswered question for this week.

        A question counts as answered if a session recorded it (device) or a
        saved story carries its text (web — the web never wrote sessions, so
        it offered the same first question all week)."""
        week = self.get_current_week()
        questions = self.get_week_questions(week)

        if not questions:
            return None

        # Check which ones were already answered
        answered_ids = set()
        if user_id:
            conn = self.db._get_connection()
            try:
                rows = conn.execute(
                    "SELECT question_id FROM question_sessions WHERE user_id = ? AND week = ? AND answered = 1",
                    (user_id, week)
                ).fetchall()
                answered_ids = {r[0] for r in rows}
                if tenant_id:
                    asked = {(r[0] or "").strip().lower() for r in conn.execute(
                        "SELECT question_text FROM stories WHERE tenant_id = ? "
                        "AND question_text IS NOT NULL", (tenant_id,)).fetchall()}
                    answered_ids |= {q.get("id") for q in questions
                                     if (q.get("question") or "").strip().lower() in asked}
            finally:
                if not self.db._conn:
                    conn.close()

        # Find first unanswered
        for q in questions:
            if q.get("id") not in answered_ids:
                return q

        # All answered for this week
        return None

    def record_answer(self, question: Dict, answer_text: str = None,
                      audio_s3_key: str = None, user_id: int = None) -> int:
        """Record an answer to a question."""
        return self.db.save_question_session(
            question_id=question.get("id", ""),
            question_text=question.get("question", ""),
            answer_text=answer_text,
            audio_s3_key=audio_s3_key,
            week=question.get("week", self.get_current_week()),
            theme=question.get("theme", "general"),
            user_id=user_id,
        )

    def get_progress(self, user_id: int = None) -> Dict:
        """Get question progress for this week."""
        week = self.get_current_week()
        total = len(self.get_week_questions(week))

        answered = 0
        if user_id:
            conn = self.db._get_connection()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM question_sessions WHERE user_id = ? AND week = ? AND answered = 1",
                    (user_id, week)
                ).fetchone()
                answered = row[0] if row else 0
            finally:
                if not self.db._conn:
                    conn.close()

        return {
            "week": week,
            "total": total,
            "answered": answered,
            "remaining": total - answered,
        }
