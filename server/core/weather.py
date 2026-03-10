"""
Weather service for Polly Connect.
Real weather via Weather.gov (free, no API key) + Farmer's Almanac fun facts.
Uses IP geolocation to auto-detect location.
"""

import asyncio
import json
import logging
import os
import random
import time
import urllib.request
import urllib.error
from datetime import datetime
from typing import Dict, Optional, Tuple

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

# Cache duration for weather data (2 hours)
WEATHER_CACHE_TTL = 2 * 60 * 60


def _http_get_json(url: str, timeout: int = 10) -> Optional[Dict]:
    """Simple HTTP GET that returns parsed JSON."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "PollyConnect/1.0 (polly-connect.com)",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.warning(f"HTTP request failed for {url}: {e}")
        return None


def _ip_to_latlon(ip: str) -> Optional[Tuple[float, float, str]]:
    """Get lat/lon/city from IP using ip-api.com (free, no key)."""
    # Skip local/private IPs
    if ip in ("127.0.0.1", "::1", "localhost") or ip.startswith("192.168.") or ip.startswith("10."):
        return None
    data = _http_get_json(f"http://ip-api.com/json/{ip}?fields=status,lat,lon,city,regionName")
    if data and data.get("status") == "success":
        city = data.get("city", "")
        region = data.get("regionName", "")
        location_name = f"{city}, {region}" if city and region else city or region or "your area"
        return (data["lat"], data["lon"], location_name)
    return None


def _get_weather_gov(lat: float, lon: float) -> Optional[Dict]:
    """
    Get current conditions + forecast from Weather.gov.
    Two-step: /points → /forecast and /stations for current conditions.
    """
    # Step 1: Get grid point
    points = _http_get_json(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}")
    if not points or "properties" not in points:
        return None

    props = points["properties"]
    forecast_url = props.get("forecast")
    station_url = props.get("observationStations")

    result = {"location": f"{props.get('relativeLocation', {}).get('properties', {}).get('city', '')}, {props.get('relativeLocation', {}).get('properties', {}).get('state', '')}"}

    # Step 2: Get forecast (7-day)
    if forecast_url:
        forecast = _http_get_json(forecast_url)
        if forecast and "properties" in forecast:
            periods = forecast["properties"].get("periods", [])
            if periods:
                result["current_period"] = periods[0]  # "Today" or "Tonight"
                result["periods"] = periods[:6]  # Next 3 days (day+night)

    # Step 3: Get current conditions from nearest station
    if station_url:
        stations = _http_get_json(station_url)
        if stations and "features" in stations:
            station_list = stations.get("features", [])
            if station_list:
                station_id = station_list[0]["properties"]["stationIdentifier"]
                obs = _http_get_json(f"https://api.weather.gov/stations/{station_id}/observations/latest")
                if obs and "properties" in obs:
                    obs_props = obs["properties"]
                    # Temperature (C to F)
                    temp_c = obs_props.get("temperature", {}).get("value")
                    if temp_c is not None:
                        result["current_temp_f"] = round(temp_c * 9 / 5 + 32)
                    # Conditions
                    result["current_desc"] = obs_props.get("textDescription", "")
                    # Humidity
                    humidity = obs_props.get("relativeHumidity", {}).get("value")
                    if humidity is not None:
                        result["humidity"] = round(humidity)
                    # Wind
                    wind_speed = obs_props.get("windSpeed", {}).get("value")
                    if wind_speed is not None:
                        result["wind_mph"] = round(wind_speed * 0.621371)

    return result


_STATE_ABBREVS = {
    "al": "Alabama", "ak": "Alaska", "az": "Arizona", "ar": "Arkansas",
    "ca": "California", "co": "Colorado", "ct": "Connecticut", "de": "Delaware",
    "fl": "Florida", "ga": "Georgia", "hi": "Hawaii", "id": "Idaho",
    "il": "Illinois", "in": "Indiana", "ia": "Iowa", "ks": "Kansas",
    "ky": "Kentucky", "la": "Louisiana", "me": "Maine", "md": "Maryland",
    "ma": "Massachusetts", "mi": "Michigan", "mn": "Minnesota", "ms": "Mississippi",
    "mo": "Missouri", "mt": "Montana", "ne": "Nebraska", "nv": "Nevada",
    "nh": "New Hampshire", "nj": "New Jersey", "nm": "New Mexico", "ny": "New York",
    "nc": "North Carolina", "nd": "North Dakota", "oh": "Ohio", "ok": "Oklahoma",
    "or": "Oregon", "pa": "Pennsylvania", "ri": "Rhode Island", "sc": "South Carolina",
    "sd": "South Dakota", "tn": "Tennessee", "tx": "Texas", "ut": "Utah",
    "vt": "Vermont", "va": "Virginia", "wa": "Washington", "wv": "West Virginia",
    "wi": "Wisconsin", "wy": "Wyoming", "dc": "District of Columbia",
}


def _expand_state_abbrev(location: str) -> str:
    """Expand 'Hartland, WI' → 'Hartland, Wisconsin' for TTS."""
    if not location or "," not in location:
        return location
    parts = location.rsplit(",", 1)
    if len(parts) == 2:
        state = parts[1].strip().lower()
        if state in _STATE_ABBREVS:
            return f"{parts[0].strip()}, {_STATE_ABBREVS[state]}"
    return location


def get_almanac_note() -> str:
    """Return a random Almanac fun fact (instant, no API call)."""
    return random.choice(ALMANAC_NOTES)


class AlmanacWeather:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self._forecasts = []
        self._weather_cache: Dict[str, Tuple[float, Dict]] = {}  # ip -> (timestamp, data)
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
            if isinstance(data, dict) and "weeks" in data:
                self._forecasts = data["weeks"]
            else:
                self._forecasts = data
            logger.info(f"Loaded {len(self._forecasts)} almanac forecasts")
        except Exception as e:
            logger.error(f"Error loading almanac weather: {e}")

    def get_weather(self, client_ip: str = None,
                    location_override: tuple = None) -> str:
        """
        Get real weather + almanac fun fact. Falls back to almanac-only if API fails.
        location_override: (lat, lon, city_name) from user settings.
        """
        # Try user-configured location first
        if location_override:
            lat, lon, city = location_override
            weather = self._get_cached_weather_by_coords(lat, lon, city)
            if weather:
                return self._format_real_weather(weather)

        # Try IP geolocation
        if client_ip:
            weather = self._get_cached_weather(client_ip)
            if weather:
                return self._format_real_weather(weather)

        # Fallback to almanac
        return self.get_weekly_forecast()

    def _get_cached_weather_by_coords(self, lat: float, lon: float,
                                       location_name: str) -> Optional[Dict]:
        """Get weather data by coordinates with 2-hour cache."""
        now = time.time()
        cache_key = f"{lat},{lon}"

        if cache_key in self._weather_cache:
            cached_time, cached_data = self._weather_cache[cache_key]
            if now - cached_time < WEATHER_CACHE_TTL:
                logger.info(f"Weather cache hit for {location_name}")
                return cached_data

        logger.info(f"Weather lookup: {location_name} ({lat}, {lon})")
        weather = _get_weather_gov(lat, lon)
        if weather:
            weather["location_name"] = location_name
            self._weather_cache[cache_key] = (now, weather)
            return weather
        return None

    def _get_cached_weather(self, client_ip: str) -> Optional[Dict]:
        """Get weather data with 2-hour cache."""
        now = time.time()

        # Check cache
        if client_ip in self._weather_cache:
            cached_time, cached_data = self._weather_cache[client_ip]
            if now - cached_time < WEATHER_CACHE_TTL:
                logger.info(f"Weather cache hit for {client_ip}")
                return cached_data

        # Get location from IP
        location = _ip_to_latlon(client_ip)
        if not location:
            logger.info(f"Could not geolocate IP: {client_ip}")
            return None

        lat, lon, location_name = location
        logger.info(f"Weather lookup: {client_ip} → {location_name} ({lat}, {lon})")

        # Get weather from Weather.gov
        weather = _get_weather_gov(lat, lon)
        if weather:
            weather["location_name"] = location_name
            self._weather_cache[client_ip] = (now, weather)
            return weather

        return None

    def _format_real_weather(self, weather: Dict) -> str:
        """Format real weather data into brief conversational speech."""
        parts = []
        location = weather.get("location_name") or weather.get("location", "your area")
        location = _expand_state_abbrev(location)

        # Current conditions — keep it short
        temp = weather.get("current_temp_f")
        desc = weather.get("current_desc", "")
        if temp is not None:
            if desc:
                parts.append(f"In {location}, it's {temp} degrees and {desc.lower()}.")
            else:
                parts.append(f"In {location}, it's {temp} degrees.")
        elif desc:
            parts.append(f"In {location}, it's {desc.lower()}.")

        # Today's short forecast only
        current_period = weather.get("current_period")
        if current_period:
            short = current_period.get("shortForecast", "")
            high_low = current_period.get("temperature")
            name = current_period.get("name", "Today")
            if short and high_low:
                temp_word = "High" if "day" in name.lower() or name == "Today" else "Low"
                parts.append(f"{temp_word} of {high_low}, {short.lower()}.")
            elif short:
                parts.append(f"{name}: {short.lower()}.")

        # Tomorrow in one line
        periods = weather.get("periods", [])
        for p in periods[1:3]:
            name = p.get("name", "")
            if "night" not in name.lower():
                short = p.get("shortForecast", "")
                temp_val = p.get("temperature")
                if short and temp_val:
                    parts.append(f"Tomorrow, {short.lower()}, {temp_val}.")
                break

        return " ".join(parts)

    def get_weekly_forecast(self) -> str:
        """Get this week's almanac forecast (fallback when real weather unavailable)."""
        from datetime import timedelta
        now = datetime.now()

        for entry in self._forecasts:
            start = entry.get("start_date")
            if start:
                try:
                    start_dt = datetime.strptime(start, "%Y-%m-%d")
                    if start_dt <= now < start_dt + timedelta(days=7):
                        return self._format_forecast(entry)
                except ValueError:
                    continue

        week_num = now.isocalendar()[1]
        for entry in self._forecasts:
            if entry.get("week") == week_num:
                return self._format_forecast(entry)

        return self._seasonal_default(now.month)

    def _format_forecast(self, entry: dict) -> str:
        """Build a conversational forecast from rich almanac data."""
        parts = ["According to the Farmer's Almanac,"]

        forecast = entry.get("forecast", "")
        if forecast:
            parts.append(forecast[0].lower() + forecast[1:] if forecast else "")

        high = entry.get("high_range")
        low = entry.get("low_range")
        if high and low:
            parts.append(f"Highs around {high} and lows around {low}.")

        wisdom = entry.get("folk_wisdom")
        if wisdom:
            parts.append(f"And as they say, {wisdom}")

        if not parts[1:]:
            details = entry.get("details", "")
            body = f"{entry.get('forecast', '')} {details}".strip()
            return f"According to the Farmer's Almanac, {body[0].lower() + body[1:] if body else ''}"

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
