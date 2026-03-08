"""
Data loader for Polly Connect — loads jokes, questions, and config from JSON.
"""

import json
import logging
import os
import random
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class DataLoader:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.jokes: List[Dict] = []
        self.kid_jokes: List[Dict] = []
        self.questions: List[Dict] = []
        self.family_questions: List[Dict] = []
        self.config: Dict = {}

        # Flat lists for random access
        self._all_jokes: List[Dict] = []
        self._all_kid_jokes: List[Dict] = []
        self._all_questions: List[Dict] = []
        self._all_family_questions: List[Dict] = []

        self._load_jokes()
        self._load_kid_jokes()
        self._load_questions()
        self._load_family_questions()
        self._load_config()

    def _load_jokes(self):
        path = os.path.join(self.data_dir, "jokes.json")
        if not os.path.exists(path):
            logger.warning(f"Jokes file not found: {path}")
            return
        with open(path, "r", encoding="utf-8") as f:
            self.jokes = json.load(f)
        # Flatten all jokes into a single list
        for week_block in self.jokes:
            for joke in week_block.get("jokes", []):
                self._all_jokes.append(joke)
        logger.info(f"Loaded {len(self._all_jokes)} jokes")

    def _load_kid_jokes(self):
        path = os.path.join(self.data_dir, "kid_jokes.json")
        if not os.path.exists(path):
            logger.warning(f"Kid jokes file not found: {path}")
            return
        with open(path, "r", encoding="utf-8") as f:
            self._all_kid_jokes = json.load(f)
        logger.info(f"Loaded {len(self._all_kid_jokes)} kid jokes")

    def _load_questions(self):
        path = os.path.join(self.data_dir, "questions.json")
        if not os.path.exists(path):
            logger.warning(f"Questions file not found: {path}")
            return
        with open(path, "r", encoding="utf-8") as f:
            self.questions = json.load(f)
        # Flatten all questions into a single list
        for week_block in self.questions:
            for q in week_block.get("questions", []):
                q["theme"] = week_block.get("theme", "general")
                q["week"] = week_block.get("week", 0)
                self._all_questions.append(q)
        logger.info(f"Loaded {len(self._all_questions)} questions")

    def _load_family_questions(self):
        path = os.path.join(self.data_dir, "family_questions.json")
        if not os.path.exists(path):
            logger.warning(f"Family questions file not found: {path}")
            return
        with open(path, "r", encoding="utf-8") as f:
            self.family_questions = json.load(f)
        for theme_block in self.family_questions:
            for q in theme_block.get("questions", []):
                q["theme"] = theme_block.get("theme", "general")
                q["jungian_stage"] = theme_block.get("jungian_stage", "ordinary_world")
                q["life_phase"] = theme_block.get("life_phase", "childhood")
                self._all_family_questions.append(q)
        logger.info(f"Loaded {len(self._all_family_questions)} family questions")

    def _load_config(self):
        path = os.path.join(self.data_dir, "polly-config.json")
        if not os.path.exists(path):
            logger.warning(f"Config file not found: {path}")
            return
        with open(path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
        logger.info("Loaded polly-config")

    def get_joke(self) -> Optional[Dict]:
        """Return a random joke dict with 'setup' and 'punchline'."""
        if not self._all_jokes:
            return None
        return random.choice(self._all_jokes)

    def get_kid_joke(self) -> Optional[Dict]:
        """Return a random kid joke dict with 'setup' and 'punchline'."""
        if not self._all_kid_jokes:
            return None
        return random.choice(self._all_kid_jokes)

    def get_question(self) -> Optional[Dict]:
        """Return a random question dict with 'question', 'theme', 'type'."""
        if not self._all_questions:
            return None
        return random.choice(self._all_questions)

    def get_family_question(self, theme: str = None) -> Optional[Dict]:
        """Return a random family question dict, optionally filtered by theme."""
        if not self._all_family_questions:
            return None
        if theme:
            themed = [q for q in self._all_family_questions if q.get("theme") == theme]
            if themed:
                return random.choice(themed)
        return random.choice(self._all_family_questions)

    def get_config(self, section: str = None) -> Dict:
        """Return full config or a specific section."""
        if section:
            return self.config.get(section, {})
        return self.config

    def get_response(self, category: str) -> Optional[str]:
        """Return a random response string from polly-config responses section."""
        responses = self.config.get("responses", {}).get(category, [])
        if not responses:
            return None
        return random.choice(responses)

    def get_trigger_phrases(self, intent: str) -> List[str]:
        """Return trigger phrases for a given intent from polly-config."""
        return self.config.get("trigger_phrases", {}).get(intent, [])

    def stats(self) -> str:
        return (f"{len(self._all_jokes)} jokes, {len(self._all_questions)} questions, "
                f"{len(self._all_family_questions)} family questions")
