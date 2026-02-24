"""
Medication reminder system for Polly Connect.
Background scheduler checks medication times every minute,
pushes reminders through existing WebSocket connections.
"""

import asyncio
import json
import logging
from datetime import datetime, time
from typing import Optional

logger = logging.getLogger(__name__)


class MedicationScheduler:
    def __init__(self, db):
        self.db = db
        self._running = False
        self._websockets = {}  # device_id -> websocket
        self._task = None

    def register_websocket(self, device_id: str, websocket):
        """Track active WebSocket connections for push reminders."""
        self._websockets[device_id] = websocket

    def unregister_websocket(self, device_id: str):
        self._websockets.pop(device_id, None)

    async def start(self):
        """Start the background medication check loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info("Medication scheduler started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _check_loop(self):
        """Check medication schedules every 60 seconds."""
        while self._running:
            try:
                await self._check_medications()
            except Exception as e:
                logger.error(f"Medication check error: {e}")
            await asyncio.sleep(60)

    async def _check_medications(self):
        """Check if any medications are due now."""
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        current_day = now.strftime("%a").lower()

        meds = self.db.get_medications()
        for med in meds:
            times = json.loads(med["times"]) if isinstance(med["times"], str) else med["times"]
            active_days = json.loads(med["active_days"]) if isinstance(med["active_days"], str) else med["active_days"]

            if current_day not in active_days:
                continue

            for med_time in times:
                if med_time == current_time:
                    await self._send_reminder(med)

    async def _send_reminder(self, med: dict):
        """Push medication reminder to all connected devices."""
        name = med["name"]
        dosage = med.get("dosage", "")
        msg = f"Time to take your {name}"
        if dosage:
            msg += f", {dosage}"
        msg += ". Did you take it?"

        logger.info(f"Medication reminder: {msg}")

        for device_id, ws in list(self._websockets.items()):
            try:
                await ws.send_json({
                    "event": "medication_reminder",
                    "text": msg,
                    "medication_id": med["id"],
                    "medication_name": name,
                })
            except Exception:
                self.unregister_websocket(device_id)

        # Log the reminder
        self.db.log_medication(med["id"], "reminded", reminder_count=1)

    def parse_medication_command(self, text: str) -> Optional[dict]:
        """Parse medication-related voice commands."""
        text_lower = text.lower()

        # "remind me to take aspirin at 8am and 8pm"
        import re
        add_match = re.search(
            r"remind me to take (.+?) at (.+)", text_lower
        )
        if add_match:
            name = add_match.group(1).strip()
            time_str = add_match.group(2).strip()
            # Parse times like "8am and 8pm" or "8:00, 20:00"
            times = self._parse_times(time_str)
            return {"action": "add", "name": name, "times": times}

        # "what medications do I take"
        if "what medication" in text_lower or "my pills" in text_lower:
            return {"action": "list"}

        # "did I take my pills" / "yes I took it"
        if "took" in text_lower or "yes" in text_lower or "taken" in text_lower:
            return {"action": "confirm_taken"}

        return None

    def _parse_times(self, time_str: str) -> list:
        """Parse time strings like '8am and 8pm' into ['08:00', '20:00']."""
        import re
        times = []
        # Find patterns like 8am, 8:00am, 20:00
        matches = re.findall(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', time_str.lower())
        for hour, minute, period in matches:
            h = int(hour)
            m = int(minute) if minute else 0
            if period == "pm" and h < 12:
                h += 12
            elif period == "am" and h == 12:
                h = 0
            times.append(f"{h:02d}:{m:02d}")
        return times if times else ["08:00"]
