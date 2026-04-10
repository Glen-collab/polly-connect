"""
Conversation state management for Polly Connect.
Tracks per-device conversation mode for family storytelling flow.
"""

import time
from enum import Enum
from typing import Dict, List, Optional


class ConversationMode(Enum):
    COMMAND = "command"                        # Normal wake-word mode
    STORY_PROMPT = "story_prompt"              # Asked a question, waiting for answer
    STORY_LISTEN = "story_listen"              # User is telling a story
    FOLLOWUP_WAIT = "followup_wait"            # Asked follow-up, waiting for answer
    AWAITING_RELATIONSHIP = "awaiting_relationship"  # Asked how they know the owner
    AWAITING_NAME = "awaiting_name"            # Asked "who is this?" for message board
    STORY_RECORD = "story_record"              # Button-triggered WAV recording mode
    AWAITING_POLLY_MESSAGE = "awaiting_polly_message"  # Waiting for message to send to friend's Polly


# Dynamic timeouts per mode
# Generous silence timeouts so elderly users can pause and think
SILENCE_TIMEOUTS = {
    ConversationMode.COMMAND: 2.0,
    ConversationMode.STORY_PROMPT: 8.0,
    ConversationMode.STORY_LISTEN: 8.0,
    ConversationMode.FOLLOWUP_WAIT: 8.0,
    ConversationMode.AWAITING_RELATIONSHIP: 8.0,
    ConversationMode.AWAITING_NAME: 8.0,
    ConversationMode.AWAITING_POLLY_MESSAGE: 8.0,
    ConversationMode.STORY_RECORD: 15.0,       # Extra generous — button stops it, not silence
}

MAX_RECORDING_TIMES = {
    ConversationMode.COMMAND: 10.0,
    ConversationMode.STORY_PROMPT: 300.0,
    ConversationMode.STORY_LISTEN: 300.0,
    ConversationMode.FOLLOWUP_WAIT: 300.0,
    ConversationMode.AWAITING_RELATIONSHIP: 30.0,
    ConversationMode.AWAITING_NAME: 30.0,
    ConversationMode.AWAITING_POLLY_MESSAGE: 60.0,  # 1 min to say your message
    ConversationMode.STORY_RECORD: 1800.0,     # 30 minutes max
}


class ConversationState:
    """Tracks the current conversation state for a single device/session."""

    def __init__(self):
        self._mode: ConversationMode = ConversationMode.COMMAND
        self.mode_set_at: float = time.monotonic()
        self.speaker_name: Optional[str] = None
        self.current_question: Optional[str] = None
        self.story_parts: List[str] = []
        self.followup_count: int = 0
        self.max_followups: int = 3
        # Narrative arc context
        self.current_bucket: Optional[str] = None      # Jungian bucket
        self.current_life_phase: Optional[str] = None   # Life phase
        self.critical_thinking_step: int = 1             # 1-6
        # Message board pending status
        self.pending_status: Optional[str] = None
        # Cross-tenant message target
        self.pending_polly_target: Optional[Dict] = None  # {"tenant_id": int, "name": str, "person": str}
        # Multi-tenant context (device-level, persists across reset)
        self.tenant_id: Optional[int] = None
        self.user_id: Optional[int] = None
        # Client IP for location-based services (weather)
        self.client_ip: Optional[str] = None
        # Voice volume (10-100%, persists across reset)
        self.voice_volume: int = 100

    @property
    def mode(self) -> ConversationMode:
        return self._mode

    @mode.setter
    def mode(self, value: ConversationMode):
        self._mode = value
        self.mode_set_at = time.monotonic()

    def reset(self):
        self.mode = ConversationMode.COMMAND
        self.speaker_name = None
        self.current_question = None
        self.story_parts = []
        self.followup_count = 0
        self.current_bucket = None
        self.current_life_phase = None
        self.critical_thinking_step = 1
        self.pending_status = None
        self.pending_polly_target = None
        # tenant_id and user_id intentionally NOT reset (device-level)

    def soft_reset(self, max_age_seconds: float = 300.0):
        """Reset only if conversational state is stale (>5 min old).
        Preserves STORY_PROMPT/FOLLOWUP_WAIT across brief reconnects
        so users don't lose their answer when WiFi blips."""
        if self.is_conversational and self.mode_set_at > 0:
            age = time.monotonic() - self.mode_set_at
            if age < max_age_seconds:
                return  # Keep conversational state — user may still be answering
        self.reset()

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
            ConversationMode.AWAITING_RELATIONSHIP,
            ConversationMode.AWAITING_NAME,
            ConversationMode.AWAITING_POLLY_MESSAGE,
            ConversationMode.STORY_RECORD,
        )
