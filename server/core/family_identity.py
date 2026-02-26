"""
Family identity service for Polly Connect.
Handles visitor introductions, family member registration, and recognition.
"""

import logging
import re
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class FamilyIdentityService:
    """Manages family member registration and recognition."""

    def __init__(self, db):
        self.db = db

    def register_member(self, name: str, relationship: str = None,
                        primary_user_id: int = None) -> Dict:
        """Register or update a family member. Returns member info."""
        member_id = self.db.add_family_member(name, relationship, primary_user_id)
        member = self.db.find_family_member(name)
        if member:
            logger.info(f"Family member registered/updated: {name} (visit #{member['visit_count']})")
        return member or {"id": member_id, "name": name, "relationship": relationship, "visit_count": 1}

    def recognize_member(self, name: str) -> Optional[Dict]:
        """Try to find a known family member by name (fuzzy match)."""
        member = self.db.find_family_member(name)
        if member:
            self.db.update_family_member_visit(member["id"])
            logger.info(f"Recognized family member: {name}")
        return member

    def parse_introduction(self, text: str) -> Optional[Tuple[str, Optional[str]]]:
        """
        Extract name and relationship from introduction text.
        Returns (name, relationship) or None if no introduction detected.

        Examples:
          "this is Sandy, I'm Evelyn's daughter" -> ("Sandy", "Evelyn's daughter")
          "my name is John" -> ("John", None)
          "I'm Mary, her granddaughter" -> ("Mary", "her granddaughter")
        """
        text_lower = text.lower().strip()

        # Filter out false positives — common non-introduction phrases
        false_positives = [
            "this is great", "this is good", "this is nice", "this is fun",
            "this is hard", "this is easy", "this is it", "this is all",
            "this is where", "this is what", "this is how", "this is why",
            "this is the", "this is my", "this is a", "this is an",
        ]
        for fp in false_positives:
            if text_lower.startswith(fp):
                return None

        name = None
        relationship = None

        # Pattern: "this is [Name]" or "this is [Name], [relationship]"
        match = re.search(
            r"this is ([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)"
            r"(?:,?\s+(?:I'?m|she'?s|he'?s|they'?re)\s+(.+))?",
            text, re.IGNORECASE
        )
        if match:
            name = match.group(1).strip().title()
            relationship = match.group(2).strip() if match.group(2) else None
            return (name, relationship)

        # Pattern: "my name is [Name]"
        match = re.search(
            r"my name is ([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)",
            text, re.IGNORECASE
        )
        if match:
            name = match.group(1).strip().title()
            return (name, None)

        # Pattern: "I'm [Name]" (but NOT "I'm fine", "I'm good", etc.)
        skip_words = {
            "fine", "good", "great", "okay", "ok", "doing", "here", "ready",
            "back", "home", "tired", "hungry", "happy", "sad", "sorry",
            "not", "just", "going", "looking", "trying", "telling",
        }
        match = re.search(r"I'?m\s+([A-Z][a-z]+)", text)
        if match:
            candidate = match.group(1).strip()
            if candidate.lower() not in skip_words:
                name = candidate.title()
                # Check for trailing relationship: "I'm Sandy, Evelyn's daughter"
                rel_match = re.search(
                    r"I'?m\s+" + re.escape(candidate) + r",?\s+(.+)",
                    text, re.IGNORECASE
                )
                if rel_match:
                    relationship = rel_match.group(1).strip()
                return (name, relationship)

        return None

    def build_greeting(self, name: str, relationship: str = None,
                       visit_count: int = 1) -> str:
        """Build a warm greeting for a family member."""
        if visit_count > 1:
            greetings = [
                f"Hey {name}! Good to hear from you again.",
                f"Welcome back, {name}! It's nice to talk to you again.",
                f"{name}! So glad you came back to visit.",
            ]
            import random
            greeting = random.choice(greetings)
            if relationship:
                greeting += f" I remember you're {relationship}."
            return greeting
        else:
            if relationship:
                return f"Nice to meet you, {name}! I'll remember you're {relationship}."
            return f"Nice to meet you, {name}! I'll remember you."
