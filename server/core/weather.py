"""
Farmer's Almanac Weather for Polly Connect.
Pre-loaded seasonal forecasts — no API calls needed.
"""

import json
import logging
import os
import random
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

ALMANAC_NOTES = [
    "The Farmer's Almanac has been predicting weather since 1818 — over 200 years of wisdom passed down through generations.",
    "Did you know the Farmer's Almanac uses a secret formula based on sunspot activity, tidal action, and planetary positions?",
    "The Farmer's Almanac claims about an 80 percent accuracy rate — not bad for a tradition that started before modern weather stations.",
    "Benjamin Franklin published the first American almanac, Poor Richard's Almanack, way back in 1732.",
    "Farmers used to plan their entire planting season around the almanac — and many still do today.",
    "The original Farmer's Almanac formula is locked in a black tin box at the publisher's office in Lewiston, Maine.",
    "During the War of 1812, the Farmer's Almanac correctly predicted a summer snowstorm — and people thought it was a misprint!",
    "There are actually two almanacs — the Farmer's Almanac and the Old Farmer's Almanac — and they've been friendly rivals since 1818.",
    "The almanac doesn't just cover weather — it's got planting charts, moon phases, fishing tables, and even home remedies.",
    "Many old-timers swear by the almanac more than the TV weatherman — and honestly, sometimes they're right!",
    "The Farmer's Almanac makes its predictions two years in advance. Imagine trying to guess the weather that far out!",
    "Abraham Lincoln once used the almanac as evidence in a murder trial — he proved the moon wasn't bright enough for a witness to see what they claimed.",
]


class AlmanacWeather:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self._forecasts = []
        self._load_forecasts()

    def _load_forecasts(self):
        """Load almanac weather from JSON if available."""
        path = os.path.join(self.data_dir, "almanac_weather.json")
        if not os.path.exists(path):
            logger.info("almanac_weather.json not found — using built-in seasonal defaults")
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Support both {"weeks": [...]} and flat array formats
            if isinstance(data, dict) and "weeks" in data:
                self._forecasts = data["weeks"]
            else:
                self._forecasts = data
            logger.info(f"Loaded {len(self._forecasts)} almanac forecasts")
        except Exception as e:
            logger.error(f"Error loading almanac weather: {e}")

    def get_weekly_forecast(self) -> str:
        """Get this week's forecast."""
        from datetime import timedelta
        now = datetime.now()

        # Try to match by start_date first (handles year-spanning data)
        for entry in self._forecasts:
            start = entry.get("start_date")
            if start:
                try:
                    start_dt = datetime.strptime(start, "%Y-%m-%d")
                    if start_dt <= now < start_dt + timedelta(days=7):
                        return self._format_forecast(entry)
                except ValueError:
                    continue

        # Fallback: match by ISO week number
        week_num = now.isocalendar()[1]
        for entry in self._forecasts:
            if entry.get("week") == week_num:
                return self._format_forecast(entry)

        # Last resort: seasonal defaults
        return self._seasonal_default(now.month)

    def _format_forecast(self, entry: dict) -> str:
        """Build a conversational forecast from rich almanac data."""
        parts = ["According to the Farmer's Almanac,"]

        forecast = entry.get("forecast", "")
        if forecast:
            # Lowercase the first letter to flow after "According to..."
            parts.append(forecast[0].lower() + forecast[1:] if forecast else "")

        high = entry.get("high_range")
        low = entry.get("low_range")
        if high and low:
            parts.append(f"Highs around {high} and lows around {low}.")

        wisdom = entry.get("folk_wisdom")
        if wisdom:
            parts.append(f"And as they say, {wisdom}")

        # Fallback for simple format
        if not parts[1:]:
            details = entry.get("details", "")
            body = f"{entry.get('forecast', '')} {details}".strip()
            return f"According to the Farmer's Almanac, {body[0].lower() + body[1:] if body else ''}"

        # Add a fun almanac note at the end
        parts.append(random.choice(ALMANAC_NOTES))

        return " ".join(parts)

    def _seasonal_default(self, month: int) -> str:
        """Friendly seasonal weather when no specific data loaded."""
        note = random.choice(ALMANAC_NOTES)
        if month in (12, 1, 2):
            return f"According to the Farmer's Almanac, it's wintertime. Bundle up warm if you head outside. Perfect weather for a cup of cocoa by the window. {note}"
        elif month in (3, 4, 5):
            return f"According to the Farmer's Almanac, spring is in the air. Flowers are starting to bloom and the birds are singing. A lovely time to sit on the porch. {note}"
        elif month in (6, 7, 8):
            return f"According to the Farmer's Almanac, it's summertime. Stay hydrated and enjoy the warm sunshine. Great weather for watching the garden grow. {note}"
        else:
            return f"According to the Farmer's Almanac, it's autumn. The leaves are changing colors. A beautiful time of year to enjoy the view outside. {note}"
