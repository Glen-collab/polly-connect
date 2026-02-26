"""
Conversation state management for Polly Connect.
Tracks per-device conversation mode for family storytelling flow.
"""

from enum import Enum
from typing import List, Optional


class ConversationMode(Enum):
    COMMAND = "command"              # Normal wake-word mode
    STORY_PROMPT = "story_prompt"    # Asked a question, waiting for answer
    STORY_LISTEN = "story_listen"    # User is telling a story
    FOLLOWUP_WAIT = "followup_wait"  # Asked follow-up, waiting for answer


# Dynamic timeouts per mode
SILENCE_TIMEOUTS = {
    ConversationMode.COMMAND: 1.5,
    ConversationMode.STORY_PROMPT: 8.0,
    ConversationMode.STORY_LISTEN: 4.0,
    ConversationMode.FOLLOWUP_WAIT: 6.0,
}

MAX_RECORDING_TIMES = {
    ConversationMode.COMMAND: 10.0,
    ConversationMode.STORY_PROMPT: 300.0,
    ConversationMode.STORY_LISTEN: 300.0,
    ConversationMode.FOLLOWUP_WAIT: 300.0,
}


class ConversationState:
    """Tracks the current conversation state for a single device/session."""

    def __init__(self):
        self.mode: ConversationMode = ConversationMode.COMMAND
        self.speaker_name: Optional[str] = None
        self.current_question: Optional[str] = None
        self.story_parts: List[str] = []
        self.followup_count: int = 0
        self.max_followups: int = 3
        # Narrative arc context
        self.current_bucket: Optional[str] = None      # Jungian bucket
        self.current_life_phase: Optional[str] = None   # Life phase
        self.critical_thinking_step: int = 1             # 1-6

    def reset(self):
        self.mode = ConversationMode.COMMAND
        self.speaker_name = None
        self.current_question = None
        self.story_parts = []
        self.followup_count = 0
        self.current_bucket = None
        self.current_life_phase = None
        self.critical_thinking_step = 1

    @property
    def silence_timeout(self) -> float:
        return SILENCE_TIMEOUTS.get(self.mode, 1.5)

    @property
    def max_recording(self) -> float:
        return MAX_RECORDING_TIMES.get(self.mode, 10.0)

    @property
    def needs_wake_word(self) -> bool:
        return self.mode == ConversationMode.COMMAND

    @property
    def is_conversational(self) -> bool:
        return self.mode in (
            ConversationMode.STORY_PROMPT,
            ConversationMode.STORY_LISTEN,
            ConversationMode.FOLLOWUP_WAIT,
        )
