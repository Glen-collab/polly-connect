"""
Follow-up question generator for Polly Connect.
After each answer, generates contextual follow-up questions using OpenAI.
"""

import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


class FollowupGenerator:
    """Generate contextual follow-up questions based on user's answer."""

    def __init__(self):
        self._available = bool(OPENAI_API_KEY)
        self._client = None

        if self._available:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=OPENAI_API_KEY)
                logger.info("OpenAI follow-up generator initialized")
            except ImportError:
                self._available = False
                logger.warning("openai package not installed — follow-ups disabled")

    @property
    def available(self) -> bool:
        return self._available and self._client is not None

    async def generate(self, original_question: str, answer_text: str,
                       count: int = 3) -> List[str]:
        """
        Generate follow-up questions based on the user's answer.
        Returns a list of question strings.
        """
        if not self.available or not answer_text:
            return []

        try:
            import asyncio
            response = await asyncio.to_thread(self._call_openai, original_question, answer_text, count)
            return response
        except Exception as e:
            logger.error(f"Follow-up generation error: {e}")
            return []

    def _call_openai(self, question: str, answer: str, count: int) -> List[str]:
        """Synchronous OpenAI API call."""
        prompt = f"""You are Polly, a warm companion for an elderly person recording their life stories.

The person was asked: "{question}"
They answered: "{answer}"

Generate {count} warm, gentle follow-up questions that dig deeper into their story.
Keep questions simple, one sentence each. Be encouraging and curious.
Return only the questions, one per line, no numbering."""

        response = self._client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.7,
        )

        text = response.choices[0].message.content.strip()
        questions = [q.strip() for q in text.split("\n") if q.strip()]
        return questions[:count]
