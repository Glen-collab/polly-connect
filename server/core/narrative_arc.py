"""
Jungian Narrative Arc management for Polly Connect.

Maps the Hero's Journey to family storytelling, tracks bucket coverage,
and guides question selection toward uncovered narrative areas.

6-stage arc: Ordinary World → Call to Adventure → Crossing Threshold
  → Trials/Allies/Enemies → Transformation → Return with Knowledge

6 critical thinking steps: Observe → Recall → Feel → Change → Relate → Reflect
"""

import logging
import random
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class JungianBucket(Enum):
    ORDINARY_WORLD = "ordinary_world"
    CALL_TO_ADVENTURE = "call_to_adventure"
    CROSSING_THRESHOLD = "crossing_threshold"
    TRIALS_ALLIES_ENEMIES = "trials_allies_enemies"
    TRANSFORMATION = "transformation"
    RETURN_WITH_KNOWLEDGE = "return_with_knowledge"


class LifePhase(Enum):
    CHILDHOOD = "childhood"
    ADOLESCENCE = "adolescence"
    YOUNG_ADULT = "young_adult"
    ADULT = "adult"
    MIDLIFE = "midlife"
    ELDER = "elder"
    REFLECTION = "reflection"


# ── Critical Thinking Steps mapped to narrative arc ──

CRITICAL_THINKING_STEPS = {
    1: {
        "name": "observe",
        "description": "Establish the scene — who, what, where",
        "buckets": [JungianBucket.ORDINARY_WORLD],
        "prompts": [
            "Where were you?",
            "Who was with you?",
            "What was a normal day like around that time?",
            "Can you describe what things looked like?",
        ],
    },
    2: {
        "name": "recall",
        "description": "Surface the specific memory",
        "buckets": [JungianBucket.ORDINARY_WORLD, JungianBucket.CALL_TO_ADVENTURE],
        "prompts": [
            "What happened that stands out?",
            "What's the part you remember most clearly?",
            "What was the first thing you noticed?",
        ],
    },
    3: {
        "name": "feel",
        "description": "Explore emotional response",
        "buckets": [JungianBucket.CALL_TO_ADVENTURE],
        "prompts": [
            "How did that make you feel?",
            "What was going through your mind?",
            "Did it surprise you?",
        ],
    },
    4: {
        "name": "change",
        "description": "Identify the turning point",
        "buckets": [JungianBucket.CROSSING_THRESHOLD],
        "prompts": [
            "What changed for you in that moment?",
            "How did it shape your choices after that?",
            "Was there a before and after?",
        ],
    },
    5: {
        "name": "relate",
        "description": "Place memory in social context",
        "buckets": [JungianBucket.TRIALS_ALLIES_ENEMIES, JungianBucket.TRANSFORMATION],
        "prompts": [
            "Who influenced you then?",
            "How did others see this moment?",
            "Did anyone help you through it?",
            "Was there someone who made it harder?",
        ],
    },
    6: {
        "name": "reflect",
        "description": "Extract wisdom and legacy",
        "buckets": [JungianBucket.TRANSFORMATION, JungianBucket.RETURN_WITH_KNOWLEDGE],
        "prompts": [
            "How do you see yourself differently now?",
            "What lesson would you pass on?",
            "If a family member heard this story, what would you want them to understand?",
            "What responsibility emerged from that moment?",
            "What did that moment demand of you?",
            "What did you have to sacrifice to move forward?",
        ],
    },
}

# Warm questions per Jungian stage — used when follow-ups need arc guidance
STAGE_QUESTIONS = {
    JungianBucket.ORDINARY_WORLD: [
        "Paint me a picture — what did a regular day look like back then?",
        "If I walked into your house back then, what would I see?",
        "What sounds do you remember from that time?",
        "Who was always around?",
        "What did the mornings feel like?",
    ],
    JungianBucket.CALL_TO_ADVENTURE: [
        "Was there a moment when everything shifted?",
        "When did you first realize things were going to be different?",
        "What was the thing that made you sit up and pay attention?",
        "Was there a knock on the door that changed things?",
    ],
    JungianBucket.CROSSING_THRESHOLD: [
        "What was the hardest decision you had to make?",
        "When did you know there was no going back?",
        "What did you leave behind?",
        "What gave you the courage to step forward?",
    ],
    JungianBucket.TRIALS_ALLIES_ENEMIES: [
        "Who stood by you when it got tough?",
        "Was there somebody who surprised you — good or bad?",
        "What was the hardest part you didn't expect?",
        "Who taught you something during that time?",
    ],
    JungianBucket.TRANSFORMATION: [
        "How were you different after all that?",
        "When did you realize you'd changed?",
        "What did that experience teach you about yourself?",
        "If your younger self could see you now, what would they think?",
    ],
    JungianBucket.RETURN_WITH_KNOWLEDGE: [
        "What would you tell someone going through the same thing?",
        "What's the one thing from that experience you'd want your grandkids to know?",
        "If you could boil that whole experience down to one sentence, what would it be?",
        "How does that story shape who you are today?",
    ],
}

# Map question themes to default Jungian buckets and life phases
THEME_TO_BUCKET = {
    "family_kitchen": JungianBucket.ORDINARY_WORLD,
    "family_characters": JungianBucket.ORDINARY_WORLD,
    "holidays": JungianBucket.ORDINARY_WORLD,
    "growing_up_work": JungianBucket.CALL_TO_ADVENTURE,
    "courtship": JungianBucket.CROSSING_THRESHOLD,
    "raising_kids": JungianBucket.TRIALS_ALLIES_ENEMIES,
    "neighborhood": JungianBucket.ORDINARY_WORLD,
    "faith_and_church": JungianBucket.TRANSFORMATION,
    "music_and_fun": JungianBucket.ORDINARY_WORLD,
    "lessons_and_wisdom": JungianBucket.RETURN_WITH_KNOWLEDGE,
}

THEME_TO_LIFE_PHASE = {
    "family_kitchen": LifePhase.CHILDHOOD,
    "family_characters": LifePhase.CHILDHOOD,
    "holidays": LifePhase.CHILDHOOD,
    "growing_up_work": LifePhase.ADOLESCENCE,
    "courtship": LifePhase.YOUNG_ADULT,
    "raising_kids": LifePhase.ADULT,
    "neighborhood": LifePhase.CHILDHOOD,
    "faith_and_church": LifePhase.REFLECTION,
    "music_and_fun": LifePhase.CHILDHOOD,
    "lessons_and_wisdom": LifePhase.REFLECTION,
}


class NarrativeArc:
    """Manages the Jungian narrative arc for a speaker's story collection."""

    def __init__(self, db):
        self.db = db

    def get_bucket_coverage(self, speaker: str = None,
                             tenant_id: int = None) -> Dict[str, int]:
        """Get count of memories in each Jungian bucket for a speaker."""
        coverage = {b.value: 0 for b in JungianBucket}
        memories = self.db.get_memories(speaker=speaker, tenant_id=tenant_id)
        for mem in memories:
            bucket = mem.get("bucket", "ordinary_world")
            if bucket in coverage:
                coverage[bucket] += 1
        return coverage

    def get_life_phase_coverage(self, speaker: str = None,
                                tenant_id: int = None) -> Dict[str, int]:
        """Get count of memories in each life phase."""
        coverage = {p.value: 0 for p in LifePhase}
        memories = self.db.get_memories(speaker=speaker, tenant_id=tenant_id)
        for mem in memories:
            phase = mem.get("life_phase", "unknown")
            if phase in coverage:
                coverage[phase] += 1
        return coverage

    def get_undercovered_buckets(self, speaker: str = None,
                                 min_per_bucket: int = 3,
                                 tenant_id: int = None) -> List[str]:
        """Find buckets that need more memories."""
        coverage = self.get_bucket_coverage(speaker, tenant_id=tenant_id)
        return [bucket for bucket, count in coverage.items() if count < min_per_bucket]

    def suggest_next_bucket(self, speaker: str = None,
                            tenant_id: int = None) -> JungianBucket:
        """Suggest which narrative bucket to focus on next."""
        coverage = self.get_bucket_coverage(speaker, tenant_id=tenant_id)
        min_bucket = min(coverage, key=coverage.get)
        return JungianBucket(min_bucket)

    def suggest_next_theme(self, speaker: str = None,
                           tenant_id: int = None) -> str:
        """Suggest a question theme that fills the least-covered bucket."""
        target_bucket = self.suggest_next_bucket(speaker, tenant_id=tenant_id)
        # Find themes that map to this bucket
        matching_themes = [
            theme for theme, bucket in THEME_TO_BUCKET.items()
            if bucket == target_bucket
        ]
        if matching_themes:
            return random.choice(matching_themes)
        return random.choice(list(THEME_TO_BUCKET.keys()))

    def get_critical_thinking_step_for_bucket(self, bucket: JungianBucket) -> int:
        """Get the starting critical thinking step for a bucket."""
        for step_num, step in CRITICAL_THINKING_STEPS.items():
            if bucket in step["buckets"]:
                return step_num
        return 1

    def get_deepening_prompt(self, current_step: int) -> Optional[str]:
        """Get a follow-up prompt from the next critical thinking step."""
        next_step = current_step + 1
        if next_step in CRITICAL_THINKING_STEPS:
            prompts = CRITICAL_THINKING_STEPS[next_step]["prompts"]
            return random.choice(prompts)
        return None

    def get_stage_question(self, bucket: JungianBucket) -> str:
        """Get a warm question for a specific Jungian stage."""
        questions = STAGE_QUESTIONS.get(bucket, STAGE_QUESTIONS[JungianBucket.ORDINARY_WORLD])
        return random.choice(questions)

    def get_progress_summary(self, speaker: str = None,
                             tenant_id: int = None) -> str:
        """Generate a human-readable progress summary."""
        bucket_coverage = self.get_bucket_coverage(speaker, tenant_id=tenant_id)
        total = sum(bucket_coverage.values())

        bucket_labels = {
            "ordinary_world": "everyday life",
            "call_to_adventure": "turning points",
            "crossing_threshold": "big decisions",
            "trials_allies_enemies": "challenges and helpers",
            "transformation": "how you changed",
            "return_with_knowledge": "wisdom and lessons",
        }

        if total == 0:
            return "We haven't captured any stories yet. Ready to get started?"

        parts = []
        for bucket, count in bucket_coverage.items():
            if count > 0:
                label = bucket_labels.get(bucket, bucket)
                parts.append(f"{count} about {label}")

        gaps = []
        for bucket, count in bucket_coverage.items():
            if count == 0:
                label = bucket_labels.get(bucket, bucket)
                gaps.append(label)

        summary = f"You've shared {total} memories so far. "
        summary += "That includes " + ", ".join(parts) + ". "
        if gaps:
            summary += f"We haven't explored {gaps[0]} yet — want to go there next?"

        return summary
