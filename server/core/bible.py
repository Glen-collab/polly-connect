"""
Bible verse service for Polly Connect.
Daily verse with reflection, topic-based selection.
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class BibleVerseService:
    def __init__(self, db, data_dir: str):
        self.db = db
        self.data_dir = data_dir
        self._verses_loaded = False
        self._load_verses()

    def _load_verses(self):
        """Load bible verses from JSON into database if not already present."""
        path = os.path.join(self.data_dir, "bible_verses.json")
        if not os.path.exists(path):
            logger.info("bible_verses.json not found — bible verse feature pending data file")
            return

        # Check if verses already loaded
        verse = self.db.get_verse_by_day(1)
        if verse:
            self._verses_loaded = True
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Support both flat array and nested {months: [{weeks: [{days: []}]}]} format
            if isinstance(data, list):
                verses = data
            elif isinstance(data, dict) and "months" in data:
                verses = self._flatten_nested(data)
            else:
                verses = data

            conn = self.db._get_connection()
            try:
                for v in verses:
                    conn.execute("""
                        INSERT INTO bible_verses (reference, text, reflection, topic, day_of_year)
                        VALUES (?, ?, ?, ?, ?)
                    """, (v["reference"], v["text"], v.get("reflection", ""),
                          v.get("topic", "general"), v.get("day_of_year")))
                conn.commit()
                self._verses_loaded = True
                logger.info(f"Loaded {len(verses)} bible verses")
            finally:
                if not self.db._conn:
                    conn.close()
        except Exception as e:
            logger.error(f"Error loading bible verses: {e}")

    def _flatten_nested(self, data: dict) -> list:
        """Flatten nested month/week/day bible verse structure to flat array."""
        verses = []
        day_counter = 1
        for month in data.get("months", []):
            topic = month.get("theme", "general").lower().replace(" and ", "_").replace(" ", "_")
            for week in month.get("weeks", []):
                for day_entry in week.get("days", []):
                    verses.append({
                        "reference": day_entry.get("reference", ""),
                        "text": day_entry.get("verse", day_entry.get("text", "")),
                        "reflection": day_entry.get("reflection", ""),
                        "topic": topic,
                        "day_of_year": day_counter,
                    })
                    day_counter += 1
        return verses

    def get_daily_verse(self) -> Optional[str]:
        """Get today's bible verse with reflection."""
        day = datetime.now().timetuple().tm_yday
        verse = self.db.get_verse_by_day(day)
        if verse:
            text = f"{verse['text']} — {verse['reference']}."
            if verse.get("reflection"):
                text += f" {verse['reflection']}"
            return text
        return None

    def get_verse_by_topic(self, topic: str) -> Optional[str]:
        """Get a random verse matching a topic."""
        verse = self.db.get_verse_by_topic(topic)
        if verse:
            return f"{verse['text']} — {verse['reference']}."
        return None

    def get_verse(self, topic: str = None) -> str:
        """Main entry point — get a verse by topic or today's daily."""
        if topic:
            result = self.get_verse_by_topic(topic)
            if result:
                return result
            return f"I don't have a verse about {topic} yet, but that's a lovely topic."

        result = self.get_daily_verse()
        if result:
            return result
        return "Bible verses are being prepared. Check back soon!"
