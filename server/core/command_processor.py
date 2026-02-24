"""
Central command processor for Polly Connect.
Handles all intents with access to all services.
Tracks last_response per device for "repeat" functionality.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class CommandProcessor:
    """
    Central handler for all voice intents.
    Initialized with all service instances, called from audio.py.
    """

    def __init__(self, db, data, bible_service=None, weather_service=None,
                 med_scheduler=None):
        self.db = db
        self.data = data
        self.bible = bible_service
        self.weather = weather_service
        self.meds = med_scheduler
        self._last_response = {}

    async def process(self, intent_result: dict, raw_text: str,
                      device_id: str = "unknown") -> str:
        """Process a parsed intent and return response text."""
        intent = intent_result.get("intent", "unknown")

        # ── Memory storage ──

        if intent == "store":
            item = intent_result.get("item")
            location = intent_result.get("location")
            context = intent_result.get("context")
            if item and location:
                self.db.store_item(item, location, context, raw_text)
                resp = f"Got it. {item} is in the {location}."
                self._last_response[device_id] = resp
                return resp
            return "I didn't understand what to store."

        elif intent == "retrieve_item":
            item = intent_result.get("item")
            if item:
                results = self.db.find_item(item)
                if results:
                    r = results[0]
                    if r.get("context"):
                        resp = f"The {r['item']} is in the {r['location']}, {r['context']}."
                    else:
                        resp = f"The {r['item']} is in the {r['location']}."
                    self._last_response[device_id] = resp
                    return resp
                return f"I don't know where the {item} is."
            return "What item are you looking for?"

        elif intent == "retrieve_location":
            location = intent_result.get("location")
            if location:
                results = self.db.find_by_location(location)
                if results:
                    items = [r["item"] for r in results]
                    resp = f"In the {location}, you have: {', '.join(items)}."
                    self._last_response[device_id] = resp
                    return resp
                return f"Nothing stored in {location}."
            return "Which location?"

        elif intent == "delete":
            item = intent_result.get("item")
            if item:
                if self.db.delete_item(item):
                    return f"Forgot about the {item}."
                return f"I don't have {item} stored."
            return "What should I forget?"

        elif intent == "list_all":
            items = self.db.list_all()
            resp = f"You have {len(items)} items stored."
            self._last_response[device_id] = resp
            return resp

        # ── Jokes & questions ──

        elif intent == "tell_joke":
            joke = self.data.get_joke()
            if joke:
                resp = f"{joke['setup']} ... {joke['punchline']}"
                self._last_response[device_id] = resp
                return resp
            return "I'm fresh out of jokes right now!"

        elif intent == "ask_question":
            question = self.data.get_question()
            if question:
                resp = question["question"]
                self._last_response[device_id] = resp
                return resp
            return "I don't have any questions ready right now."

        # ── Navigation ──

        elif intent == "repeat":
            last = self._last_response.get(device_id)
            if last:
                prefix = self.data.get_response("repeat_acknowledgment") or "Sure, here it is again."
                return f"{prefix} {last}"
            return "I don't have anything to repeat."

        elif intent == "slower":
            return self.data.get_response("slower_acknowledgment") or "I'll slow down for you."

        elif intent == "skip":
            return self.data.get_response("skip_acknowledgment") or "No problem, let's move on."

        elif intent == "stop":
            return self.data.get_response("goodbye") or "Okay, take care."

        elif intent == "greeting":
            resp = self.data.get_response("greeting") or "Hello! How are you today?"
            self._last_response[device_id] = resp
            return resp

        elif intent == "goodbye":
            return self.data.get_response("goodbye") or "Goodbye, take care."

        # ── Bible verses ──

        elif intent == "bible_verse":
            if self.bible:
                topic = intent_result.get("topic")
                resp = self.bible.get_verse(topic)
                self._last_response[device_id] = resp
                return resp
            return "Bible verses are coming soon. Stay tuned!"

        # ── Medications ──

        elif intent == "medication":
            if self.meds:
                parsed = self.meds.parse_medication_command(raw_text)
                if parsed:
                    if parsed["action"] == "add":
                        import json
                        user = self.db.get_or_create_user()
                        self.db.add_medication(
                            user["id"], parsed["name"], "",
                            json.dumps(parsed["times"])
                        )
                        times_str = " and ".join(parsed["times"])
                        return f"Got it. I'll remind you to take {parsed['name']} at {times_str}."
                    elif parsed["action"] == "list":
                        meds = self.db.get_medications()
                        if meds:
                            names = [m["name"] for m in meds]
                            return f"Your medications: {', '.join(names)}."
                        return "You don't have any medication reminders set up yet."
                    elif parsed["action"] == "confirm_taken":
                        return "Great, I've noted that you took your medication."
            return "Medication reminders are coming soon."

        # ── Weather ──

        elif intent == "weather":
            if self.weather:
                resp = self.weather.get_weekly_forecast()
                self._last_response[device_id] = resp
                return resp
            return "Weather forecasts are coming soon."

        # ── Help & fallback ──

        elif intent == "help":
            resp = self.data.get_response("confused_help")
            if resp:
                self._last_response[device_id] = resp
                return resp
            return ("I can remember where things are, tell jokes, and ask you questions "
                    "about your life. Just say 'tell me a joke' or 'where are my keys'.")

        return "I didn't understand that. You can ask me to find things, tell a joke, or ask you a question."
