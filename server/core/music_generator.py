"""
Suno music generation for Polly Connect.
Monthly: collects best stories/answers, generates personalized song.
Premium tier feature.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

SUNO_API_KEY = os.getenv("SUNO_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


class MusicGenerator:
    """
    Monthly cron job:
    1. Collect best stories/answers from the month
    2. Summarize into song-worthy themes via OpenAI
    3. Generate song via Suno API in user's preferred genre
    4. Store MP3 in S3, playable via device or web app
    """

    def __init__(self, db, s3_bucket: str = None):
        self.db = db
        self.s3_bucket = s3_bucket or os.getenv("POLLY_S3_BUCKET", "polly-connect-data")
        self._available = bool(SUNO_API_KEY and OPENAI_API_KEY)

        if self._available:
            logger.info("Music generator initialized")
        else:
            logger.info("Music generator disabled (missing SUNO_API_KEY or OPENAI_API_KEY)")

    @property
    def available(self) -> bool:
        return self._available

    async def generate_monthly_song(self, user_id: int = None,
                                     genre: str = "country") -> Optional[str]:
        """
        Generate a personalized song from the month's stories.
        Returns S3 key of the generated MP3, or None.
        """
        if not self._available:
            logger.warning("Music generation not available — API keys not configured")
            return None

        # Step 1: Collect recent stories
        stories = self.db.get_stories(user_id=user_id, limit=20)
        if not stories:
            logger.info("No stories to generate song from")
            return None

        # Step 2: Summarize into themes (placeholder for OpenAI call)
        combined_text = " ".join(s.get("transcript", "") for s in stories if s.get("transcript"))
        if not combined_text:
            return None

        # TODO: Implement OpenAI summarization + Suno API integration
        # This is a premium feature that will be implemented when
        # the Suno API integration is finalized
        logger.info(f"Music generation pending: {len(stories)} stories, genre={genre}")
        return None
