"""
Prayer service for Polly Connect.
Short prayers of hope, faith, resilience, gratitude, and family.
"""

import json
import logging
import os
import random
from typing import List, Optional

logger = logging.getLogger(__name__)


class PrayerService:
    def __init__(self, data_dir: str):
        self.prayers: List[dict] = []
        self._load_prayers(data_dir)

    def _load_prayers(self, data_dir: str):
        path = os.path.join(data_dir, "prayers.json")
        if not os.path.exists(path):
            logger.warning("prayers.json not found")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.prayers = json.load(f)
            logger.info(f"Loaded {len(self.prayers)} prayers")
        except Exception as e:
            logger.error(f"Error loading prayers: {e}")

    def get_prayer(self, theme: str = None) -> str:
        if not self.prayers:
            return "Let me pray for you in my heart. You are loved."

        if theme:
            matches = [p for p in self.prayers if p.get("theme") == theme]
            if matches:
                return random.choice(matches)["text"]

        prayer = random.choice(self.prayers)
        return prayer["text"]

    def get_bedtime_prayer(self) -> str:
        bedtime = [p for p in self.prayers if p.get("occasion") == "bedtime"]
        if bedtime:
            return random.choice(bedtime)["text"]
        return self.get_prayer()
