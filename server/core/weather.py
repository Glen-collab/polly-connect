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
                self._forecasts = json.load(f)
            logger.info(f"Loaded {len(self._forecasts)} almanac forecasts")
        except Exception as e:
            logger.error(f"Error loading almanac weather: {e}")

    def get_weekly_forecast(self) -> str:
        """Get this week's forecast."""
        now = datetime.now()
        week_num = now.isocalendar()[1]

        # Try loaded data first
        for entry in self._forecasts:
            if entry.get("week") == week_num:
                forecast = entry.get("forecast", "")
                details = entry.get("details", "")
                return f"{forecast} {details}".strip()

        # Fallback: seasonal defaults
        return self._seasonal_default(now.month)

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
