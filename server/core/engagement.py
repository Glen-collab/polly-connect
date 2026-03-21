"""
Engagement tracker for Polly Connect.

Maintains long-term engagement by:
  - Tracking which topics/buckets/life phases have been explored
  - Preventing question repetition
  - Selecting questions that fill narrative gaps
  - Providing progress feedback
  - Rotating perspectives (emotion, relationships, lessons, legacy)
"""

import logging
import random
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Perspective rotation — after basic collection, revisit from these angles
PERSPECTIVE_LENSES = [
    {
        "name": "emotion",
        "label": "how you felt",
        "prompt_prefix": "Thinking about that same time — ",
        "prompts": [
            "How did that make you feel, really?",
            "Was there a moment in all that where you felt something you didn't expect?",
            "Did you ever tell anybody how you really felt about it?",
        ],
    },
    {
        "name": "relationships",
        "label": "the people involved",
        "prompt_prefix": "Going back to that time — ",
        "prompts": [
            "Who was the most important person in your life during that time?",
            "Was there somebody you wish had been there?",
            "Did that change your relationship with anybody?",
        ],
    },
    {
        "name": "lessons",
        "label": "what you learned",
        "prompt_prefix": "Looking back at all that — ",
        "prompts": [
            "What did that teach you that you couldn't have learned any other way?",
            "If you could go back knowing what you know now, would you change anything?",
            "What did that moment demand of you?",
        ],
    },
    {
        "name": "legacy",
        "label": "passing it on",
        "prompt_prefix": "Thinking about your family — ",
        "prompts": [
            "Which of these memories should a grandchild know about?",
            "Is there something from that time you want to make sure isn't forgotten?",
            "What would you want your family to understand about who you were then?",
        ],
    },
]


class EngagementTracker:
    """Tracks engagement and guides question selection for narrative depth."""

    def __init__(self, db, narrative_arc=None):
        self.db = db
        self.arc = narrative_arc
        self._asked_questions: Dict[str, Set[str]] = {}  # speaker -> set of question IDs

    def select_question(self, data_loader, speaker: str = None,
                        tenant_id: int = None) -> Optional[Dict]:
        """
        Intelligently select the next family question.

        Priority:
        1. Questions from undercovered Jungian buckets
        2. Questions from undercovered life phases
        3. Previously unasked questions
        4. Random fallback
        """
        all_questions = data_loader._all_family_questions
        if not all_questions:
            return None

        asked = self._asked_questions.get(speaker or "_default", set())

        # Filter to unasked questions
        unasked = [q for q in all_questions if q.get("id") not in asked]
        if not unasked:
            # All asked — reset and start fresh with perspective rotation
            self._asked_questions[speaker or "_default"] = set()
            unasked = all_questions

        # If we have narrative arc, prefer undercovered buckets
        if self.arc:
            target_theme = self.arc.suggest_next_theme(speaker, tenant_id=tenant_id)
            themed = [q for q in unasked if q.get("theme") == target_theme]
            if themed:
                chosen = random.choice(themed)
                self._mark_asked(speaker, chosen.get("id"))
                return chosen

        # Random from unasked
        chosen = random.choice(unasked)
        self._mark_asked(speaker, chosen.get("id"))
        return chosen

    def get_perspective_prompt(self, speaker: str = None,
                               tenant_id: int = None) -> Optional[str]:
        """
        After initial collection, offer a perspective rotation question.
        Returns a reflective prompt or None if not enough memories yet.
        """
        memories = self.db.get_memories(speaker=speaker, limit=9999,
                                       tenant_id=tenant_id)
        if len(memories) < 10:
            return None

        lens = random.choice(PERSPECTIVE_LENSES)
        prompt = random.choice(lens["prompts"])
        return f"{lens['prompt_prefix']}{prompt}"

    def get_progress_feedback(self, speaker: str = None,
                              tenant_id: int = None) -> str:
        """Generate encouraging progress feedback."""
        memories = self.db.get_memories(speaker=speaker, limit=9999,
                                       tenant_id=tenant_id)
        count = len(memories)

        if count == 0:
            return "We haven't started collecting stories yet. Ready when you are."
        elif count < 5:
            return f"You've shared {count} memories so far. Every one matters. Keep going!"
        elif count < 15:
            return (f"You've shared {count} memories! We're starting to build a real picture "
                    f"of your life. There's so much more to capture.")
        elif count < 30:
            return (f"{count} memories captured. That's a solid foundation. "
                    f"We're about a third of the way to having enough for a real book.")
        elif count < 60:
            return (f"{count} memories! You're past the halfway point. "
                    f"The story of your life is really taking shape.")
        elif count < 90:
            return (f"{count} memories. We're getting close to having enough "
                    f"for a full family legacy book. Just a bit more to go.")
        else:
            return (f"{count} memories captured. That's enough for a beautiful book. "
                    f"We can keep going, or start putting chapters together whenever you're ready.")

    def get_gap_report(self, speaker: str = None,
                       tenant_id: int = None) -> str:
        """Report on which areas of the story need more exploration."""
        if not self.arc:
            return "Story tracking is not available right now."

        undercovered = self.arc.get_undercovered_buckets(speaker, tenant_id=tenant_id)
        if not undercovered:
            return "You've covered all the major areas of your story. That's wonderful!"

        from core.narrative_arc import JungianBucket
        bucket_labels = {
            "ordinary_world": "everyday life growing up",
            "call_to_adventure": "moments that changed everything",
            "crossing_threshold": "big decisions and turning points",
            "trials_allies_enemies": "hard times and the people who helped",
            "transformation": "how you grew and changed",
            "return_with_knowledge": "wisdom and lessons for the family",
        }

        gap_labels = [bucket_labels.get(b, b) for b in undercovered[:3]]
        return (f"We could use more stories about: {', '.join(gap_labels)}. "
                f"Want to explore one of those?")

    def _mark_asked(self, speaker: str, question_id: str):
        key = speaker or "_default"
        if key not in self._asked_questions:
            self._asked_questions[key] = set()
        if question_id:
            self._asked_questions[key].add(question_id)
