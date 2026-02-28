"""
Farmer's Almanac Weather for Polly Connect.
Pre-loaded seasonal forecasts — no API calls needed.
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


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
        parts = []

        forecast = entry.get("forecast", "")
        if forecast:
            parts.append(forecast)

        high = entry.get("high_range")
        low = entry.get("low_range")
        if high and low:
            parts.append(f"Highs around {high} and lows around {low}.")

        wisdom = entry.get("folk_wisdom")
        if wisdom:
            parts.append(f"And as they say, {wisdom}")

        # Fallback for simple format
        if not parts:
            details = entry.get("details", "")
            return f"{entry.get('forecast', '')} {details}".strip()

        return " ".join(parts)

    def _seasonal_default(self, month: int) -> str:
        """Friendly seasonal weather when no specific data loaded."""
        if month in (12, 1, 2):
            return "It's wintertime. Bundle up warm if you head outside. Perfect weather for a cup of cocoa by the window."
        elif month in (3, 4, 5):
            return "Spring is in the air. Flowers are starting to bloom and the birds are singing. A lovely time to sit on the porch."
        elif month in (6, 7, 8):
            return "It's summertime. Stay hydrated and enjoy the warm sunshine. Great weather for watching the garden grow."
        else:
            return "It's autumn. The leaves are changing colors. A beautiful time of year to enjoy the view outside."
