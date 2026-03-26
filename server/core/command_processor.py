"""
Central command processor for Polly Connect.
Handles all intents with access to all services.
Tracks last_response per device for "repeat" functionality.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, Tuple

from core.conversation_state import ConversationMode, ConversationState
from config import settings

logger = logging.getLogger(__name__)


class CommandProcessor:
    """
    Central handler for all voice intents.
    Initialized with all service instances, called from audio.py.
    """

    def __init__(self, db, data, bible_service=None, prayer_service=None,
                 weather_service=None,
                 med_scheduler=None, family_identity=None, echo_engine=None,
                 memory_extractor=None, narrative_arc=None,
                 engagement=None, followup_gen=None):
        self.db = db
        self.data = data
        self.bible = bible_service
        self.prayer = prayer_service
        self.weather = weather_service
        self.meds = med_scheduler
        self.family_identity = family_identity
        self.echo_engine = echo_engine
        self.memory_extractor = memory_extractor
        self.narrative_arc = narrative_arc
        self.engagement = engagement
        self.followup_gen = followup_gen
        self._last_response = {}
        self._last_missing_item = {}  # device_id -> item name (for "found it")
        self._conversation_states = {}  # device_id -> ConversationState

    def _get_state(self, device_id: str) -> ConversationState:
        if device_id not in self._conversation_states:
            self._conversation_states[device_id] = ConversationState()
        return self._conversation_states[device_id]

    async def process(self, intent_result: dict, raw_text: str,
                      device_id: str = "unknown") -> str:
        """Process a parsed intent and return response text."""
        intent = intent_result.get("intent", "unknown")

        # ── Memory storage ──

        # Get tenant context from conversation state
        state = self._get_state(device_id)
        tid = state.tenant_id

        if intent == "store":
            from core.subscription import check_feature
            if not check_feature(self.db, tid, "add_item"):
                return "Your plan limit has been reached for stored items. Visit the Polly website to upgrade."
            item = intent_result.get("item")
            location = intent_result.get("location")
            context = intent_result.get("context")
            prep = intent_result.get("prep", "on")
            if item and location:
                self.db.store_item(item, location, context, raw_text, tenant_id=tid, prep=prep)
                verb = "are" if item.endswith("s") and not item.endswith("ss") else "is"
                resp = f"Got it. The {item} {verb} {prep} the {location}."
                self._last_response[device_id] = resp
                return resp
            return "I didn't understand what to store."

        elif intent == "retrieve_item":
            import random
            item = intent_result.get("item")
            mom = intent_result.get("mom_mode", False)
            if item:
                results = self.db.find_item(item, tenant_id=tid)
                if results:
                    if len(results) == 1:
                        r = results[0]
                        prep = r.get("prep") or "on"
                        loc = r["location"]
                        # Skip prep if location already starts with a preposition
                        loc_lower = loc.lower()
                        has_prep = loc_lower.startswith(("by ", "in ", "on ", "at ", "near ", "under ", "behind ", "next to ", "inside "))
                        if has_prep:
                            loc_phrase = loc.lower()  # "by the bathroom"
                        else:
                            loc_phrase = f"{prep} the {loc}"  # "on the shelf"
                        if mom:
                            phrases = [
                                f"Have you looked {loc_phrase}?",
                                f"Did you try {loc_phrase}?",
                                f"I think it's {loc_phrase}, sweetie.",
                                f"Check {loc_phrase}, honey.",
                                f"It should be {loc_phrase}. Did you really look?",
                                f"Last I heard, it was {loc_phrase}.",
                                f"Did you check {loc_phrase}? Really check?",
                            ]
                            resp = random.choice(phrases)
                        else:
                            verb = "are" if r['item'].endswith("s") and not r['item'].endswith("ss") else "is"
                            if r.get("context"):
                                resp = f"The {r['item']} {verb} {loc_phrase}, {r['context']}."
                            else:
                                resp = f"The {r['item']} {verb} {loc_phrase}."
                    else:
                        locations = [f"{r.get('prep', 'on')} the {r['location']}" for r in results]
                        if len(locations) == 2:
                            resp = f"Did you check {locations[0]} or {locations[1]}?"
                        else:
                            resp = f"Did you check {', '.join(locations[:-1])}, or {locations[-1]}?"
                    self._last_response[device_id] = resp
                    return resp
                # Not found — track it for "found it"
                self._last_missing_item[device_id] = item
                if mom:
                    phrases = [
                        f"Hmm, I don't remember where you put the {item}. When you find it, let me know!",
                        f"I'm not sure where the {item} is. Did you put it away properly?",
                        f"The {item}? I don't know, sweetie. Where did you last have it?",
                    ]
                    resp = random.choice(phrases)
                else:
                    resp = f"I don't know where the {item} is."
                self._last_response[device_id] = resp
                return resp
            return "What are you looking for?"

        elif intent == "found_it":
            import random
            last_item = self._last_missing_item.pop(device_id, None)
            phrases = [
                "See? It was right where I said!",
                "Good! Now put it back when you're done.",
                "Told you! Moms always know.",
                "Great! Was it in the last place you looked?",
            ]
            resp = random.choice(phrases)
            if last_item:
                resp += f" Where was the {last_item}?"
            self._last_response[device_id] = resp
            return resp

        elif intent == "play_blessing":
            import random, os
            speaker_filter = intent_result.get("speaker")
            category_filter = intent_result.get("category")

            # Get all recordings for this tenant
            recordings = self.db.get_prayer_recordings(tid)
            if not recordings:
                return "No blessings have been recorded yet. You can record one on the prayers page."

            # Filter by speaker if specified
            if speaker_filter:
                speaker_lower = speaker_filter.lower()
                filtered = [r for r in recordings if speaker_lower in (r.get("speaker_name") or "").lower()]
                if filtered:
                    recordings = filtered

            # Filter by category if specified
            if category_filter:
                filtered = [r for r in recordings if r.get("category") == category_filter]
                if filtered:
                    recordings = filtered

            # Pick one
            rec = random.choice(recordings)
            audio_file = rec.get("audio_filename")
            if not audio_file:
                return "That blessing doesn't have an audio recording."

            speaker = rec.get("speaker_name", "")
            title = rec.get("title", "a blessing")
            category = rec.get("category", "blessing")

            # Update play count
            self.db.update_prayer_recording_played(rec["id"])

            # Return special marker for audio.py to play the WAV file
            intro = f"{speaker}'s {category} blessing." if speaker else f"A {category} blessing."
            self._last_response[device_id] = intro
            return f"__PLAY_PRAYER__{audio_file}__INTRO__{intro}"

        elif intent == "retrieve_location":
            location = intent_result.get("location")
            if location:
                results = self.db.find_by_location(location, tenant_id=tid)
                if results:
                    items = [r["item"] for r in results]
                    if len(items) == 1:
                        resp = f"On the {location}, you have your {items[0]}."
                    else:
                        listed = ", ".join(items[:-1]) + f", and {items[-1]}"
                        resp = f"On the {location}, you have {len(items)} things: {listed}."
                    self._last_response[device_id] = resp
                    return resp
                return f"I don't have anything stored for {location}."
            return "Which location?"

        elif intent == "delete":
            item = intent_result.get("item")
            if item:
                if self.db.delete_item(item, tenant_id=tid):
                    return f"Forgot about the {item}."
                return f"I don't have {item} stored."
            return "What should I forget?"

        elif intent == "list_all":
            items = self.db.list_all(tenant_id=tid)
            resp = f"You have {len(items)} items stored."
            self._last_response[device_id] = resp
            return resp

        # ── Message board ──

        elif intent == "leave_message":
            person = intent_result.get("person", "")
            message = intent_result.get("message", "")
            if person and message:
                self.db.save_message(
                    from_name="someone", to_name=person,
                    message=message, tenant_id=tid
                )
                resp = f"Got it. I'll let {person} know: {message}."
                self._last_response[device_id] = resp
                return resp
            return "I didn't catch the message. Try saying: tell dad I'm going to the store."

        elif intent == "where_is_person":
            person = intent_result.get("person", "")
            if person:
                status = self.db.get_person_status(person, tenant_id=tid)
                if status:
                    created = datetime.strptime(status["created_at"], "%Y-%m-%d %H:%M:%S")
                    now = datetime.utcnow()
                    diff = now - created
                    minutes = int(diff.total_seconds() / 60)
                    if minutes < 2:
                        ago = "just a moment ago"
                    elif minutes < 60:
                        ago = f"about {minutes} minutes ago"
                    else:
                        hours = minutes // 60
                        ago = f"about {hours} hour{'s' if hours > 1 else ''} ago"
                    name = status['from_name'].title()
                    msg = self._natural_status(status['message'])
                    resp = f"Last I heard, {name} is {msg}. That was {ago}."
                    self._last_response[device_id] = resp
                    return resp
                return f"I don't have any updates on {person} right now."
            return "Who are you looking for?"

        elif intent == "status_update":
            person = intent_result.get("person")
            status_text = intent_result.get("status", "")
            if person:
                # Someone is reporting another person's status
                self.db.save_message(
                    from_name=person, message=status_text, tenant_id=tid
                )
                name = person.title()
                msg = self._natural_status(status_text)
                resp = f"Got it. {name} is {msg}. I'll post that to the board."
                self._last_response[device_id] = resp
                return resp
            else:
                # Speaker is updating their own status — need their name
                speaker = state.speaker_name
                if speaker:
                    self.db.save_message(
                        from_name=speaker, message=status_text, tenant_id=tid
                    )
                    msg = self._natural_status(status_text)
                    resp = f"Got it, {speaker}. I'll post to the board that you're {msg}."
                    self._last_response[device_id] = resp
                    return resp
                # Don't know who's speaking — ask
                state.pending_status = status_text
                state.mode = ConversationMode.AWAITING_NAME
                return "Sure, I can post that to the message board. Who is this?"

        elif intent == "check_messages":
            messages = self.db.get_messages_for(tenant_id=tid)
            if messages:
                parts = []
                for m in messages[:5]:
                    name = m['from_name'].title()
                    if m["to_name"]:
                        # Direct message — read as-is
                        parts.append(f"{name} says to {m['to_name'].title()}: {m['message']}")
                    else:
                        # Status update — add natural preposition
                        msg = self._natural_status(m['message'])
                        parts.append(f"{name} is {msg}")
                resp = f"You have {len(messages)} message{'s' if len(messages) > 1 else ''} on the board. " + ". ".join(parts) + "."
                self._last_response[device_id] = resp
                return resp
            return "The message board is clear. No messages right now."

        elif intent == "clear_messages":
            messages = self.db.get_messages_for(tenant_id=tid)
            if messages:
                conn = self.db._get_connection()
                try:
                    if tid:
                        conn.execute("DELETE FROM family_messages WHERE tenant_id = ?", (tid,))
                    else:
                        conn.execute("DELETE FROM family_messages")
                    conn.commit()
                finally:
                    if not self.db._conn:
                        conn.close()
                return f"Done. I cleared {len(messages)} message{'s' if len(messages) > 1 else ''} from the board."
            return "The board is already clear."

        elif intent == "person_home":
            person = intent_result.get("person", "")
            if person:
                self.db.clear_person_messages(person, tenant_id=tid)
                name = person.title()
                resp = f"Welcome back, {name}! I've cleared their messages from the board."
                self._last_response[device_id] = resp
                return resp
            return "Who's home?"

        # ── Jokes & questions ──

        elif intent == "tell_joke":
            # In kid mode, only serve kid jokes
            user_profile = self.db.get_or_create_user(tenant_id=tid)
            if user_profile.get("kid_mode"):
                joke = self.data.get_kid_joke()
            else:
                joke = self.data.get_joke()
            if joke:
                resp = f"<speak>{joke['setup']}<break time=\"2s\"/>{joke['punchline']}</speak>"
                self._last_response[device_id] = f"{joke['setup']} ... {joke['punchline']}"
                return resp
            return "I'm fresh out of jokes right now!"

        elif intent == "tell_naughty_joke":
            # Check kid mode
            user_profile = self.db.get_or_create_user(tenant_id=tid)
            if user_profile.get("kid_mode"):
                joke = self.data.get_kid_joke()
                if joke:
                    resp = f"<speak>How about a kid joke instead? {joke['setup']}<break time=\"2s\"/>{joke['punchline']}</speak>"
                    self._last_response[device_id] = f"{joke['setup']} ... {joke['punchline']}"
                    return resp
                return "Kid mode is on! No naughty jokes, but I'm out of kid jokes too!"
            joke = self.data.get_naughty_joke()
            if joke:
                resp = f"<speak>{joke['setup']}<break time=\"2s\"/>{joke['punchline']}</speak>"
                self._last_response[device_id] = f"{joke['setup']} ... {joke['punchline']}"
                return resp
            return "I am fresh out of naughty jokes right now!"

        elif intent == "tell_kid_joke":
            joke = self.data.get_kid_joke()
            if joke:
                resp = f"<speak>{joke['setup']}<break time=\"2s\"/>{joke['punchline']}</speak>"
                self._last_response[device_id] = f"{joke['setup']} ... {joke['punchline']}"
                return resp
            return "I don't have any kid jokes right now!"

        elif intent == "ask_question":
            owner_age = self._get_owner_age(tid)
            question = self.data.get_question(owner_age=owner_age)
            if question:
                resp = question["question"]
                self._last_response[device_id] = resp
                # Enter conversational mode so user can answer without wake word
                state = self._get_state(device_id)
                state.mode = ConversationMode.STORY_PROMPT
                state.current_question = resp
                state.story_parts = []
                state.followup_count = 0
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

        elif intent == "tell_time":
            now = datetime.now(ZoneInfo("America/Chicago"))
            hour = now.strftime("%I").lstrip("0")
            minute = now.strftime("%M")
            ampm = "AY M" if now.strftime("%p") == "AM" else "P M"
            if minute == "00":
                resp = f"It's {hour} o'clock {ampm}."
            else:
                resp = f"It's {hour} {minute} {ampm}."
            self._last_response[device_id] = resp
            return resp

        elif intent == "tell_date":
            now = datetime.now(ZoneInfo("America/Chicago"))
            resp = f"Today is {now.strftime('%A, %B')} {now.day}, {now.year}."
            self._last_response[device_id] = resp
            return resp

        elif intent == "thank_you":
            import random
            responses = [
                "You're welcome!",
                "Happy to help!",
                "Anytime!",
                "Of course! That's what I'm here for.",
                "You're very welcome!",
                "My pleasure!",
            ]
            resp = random.choice(responses)
            self._last_response[device_id] = resp
            return resp

        elif intent == "who_is":
            name = intent_result.get("name", "")
            return await self._handle_who_is(name, device_id)

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

        # ── Prayer ──

        elif intent == "prayer":
            state = self._get_state(device_id)
            theme = intent_result.get("theme")
            pray_for = intent_result.get("pray_for")

            # Check if user wants a recorded prayer (grace, bedtime, etc.)
            text_lower = raw_text.lower()
            play_recorded = any(p in text_lower for p in [
                "play grace", "say grace", "play the grace",
                "play bedtime prayer", "bedtime prayer", "bedtime blessing",
                "play morning", "morning blessing", "morning prayer",
                "play the prayer", "play a blessing", "play the blessing",
                "family grace", "family blessing", "family prayer",
                "play grandpa", "play grandma", "play papa", "play nana",
            ])

            if play_recorded:
                # Try to find a matching recorded prayer
                category = None
                if "grace" in text_lower:
                    category = "grace"
                elif "bedtime" in text_lower:
                    category = "bedtime"
                elif "morning" in text_lower:
                    category = "morning"
                elif "holiday" in text_lower:
                    category = "holiday"
                elif "blessing" in text_lower:
                    category = "blessing"

                recordings = self.db.get_prayer_recordings(
                    tid, category=category
                )
                if not recordings and category:
                    # Try all categories
                    recordings = self.db.get_prayer_recordings(tid)

                if recordings:
                    import random
                    rec = random.choice(recordings)
                    # Return special marker so audio.py knows to play the WAV file
                    speaker = rec.get("speaker_name", "")
                    title = rec.get("title", "a prayer")
                    self._last_response[device_id] = f"{speaker}'s {title}"
                    self.db.update_prayer_recording_played(rec["id"])
                    return f"__PLAY_PRAYER__{rec['audio_filename']}__INTRO__{speaker}'s {rec.get('category', 'prayer')}."

            # Fall back to AI-generated prayer
            if self.prayer:
                resp = self.prayer.get_prayer(
                    theme, tenant_id=state.tenant_id, pray_for=pray_for)
                self._last_response[device_id] = resp
                return resp
            return "Let us bow our heads. Dear Lord, be with us today. Give us strength, give us peace, and remind us that we are loved. Amen."

        # ── Nostalgia ──

        elif intent == "nostalgia":
            snippet = self.db.get_next_nostalgia_snippet(tid)
            if snippet:
                self.db.mark_nostalgia_used(snippet["id"])
                resp = snippet["text"]
                self._last_response[device_id] = resp
                return resp
            return "I don't have any nostalgia stories set up yet. Ask your family to add your hometown and birth year in the settings page, and I'll have some wonderful memories to share!"

        # ── Medications ──

        elif intent == "medication":
            if self.meds:
                parsed = self.meds.parse_medication_command(raw_text)
                if parsed:
                    if parsed["action"] == "add":
                        import json
                        user = self.db.get_or_create_user(tenant_id=tid)
                        self.db.add_medication(
                            user["id"], parsed["name"], "",
                            json.dumps(parsed["times"]), tenant_id=tid
                        )
                        times_str = " and ".join(parsed["times"])
                        return f"Got it. I'll remind you to take {parsed['name']} at {times_str}."
                    elif parsed["action"] == "list":
                        meds = self.db.get_medications(tenant_id=tid)
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
                client_ip = state.client_ip
                # Check for user-configured location
                location_override = None
                user = self.db.get_or_create_user(tenant_id=state.tenant_id)
                if user and user.get("location_lat") and user.get("location_lon"):
                    location_override = (
                        user["location_lat"],
                        user["location_lon"],
                        user.get("location_city") or "your area",
                    )
                resp = self.weather.get_weather(
                    client_ip=client_ip,
                    location_override=location_override,
                )
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

        # ── Family storytelling ──

        elif intent == "introduce_self":
            return await self._handle_introduce(intent_result, device_id)

        elif intent == "tell_story":
            return await self._handle_tell_story(device_id)

        elif intent == "hear_stories":
            return await self._handle_hear_stories(intent_result, device_id)

        elif intent == "family_question":
            return await self._handle_family_question(device_id)

        elif intent == "story_progress":
            return await self._handle_story_progress(device_id)

        return "I didn't understand that. You can ask me to find things, tell a joke, or ask you a question."

    # ── Family storytelling handlers ──

    async def _handle_introduce(self, intent_result: dict, device_id: str) -> str:
        name = intent_result.get("name")
        relationship = intent_result.get("relationship")
        if not name:
            return "I didn't catch your name. Could you say it again?"

        state = self._get_state(device_id)
        tid = state.tenant_id

        if self.family_identity:
            member = self.family_identity.register_member(name, relationship, tenant_id=tid)
            visit_count = member.get("visit_count", 1)
            state.speaker_name = name

            # If no relationship and first visit, ask how they know the owner
            if not relationship and visit_count <= 1:
                owner_name = self.db.get_owner_name(tenant_id=tid) or settings.OWNER_NAME
                state.mode = ConversationMode.AWAITING_RELATIONSHIP
                return f"Nice to meet you, {name}! How do you know {owner_name}?"

            return self.family_identity.build_greeting(name, relationship, visit_count)

        return f"Nice to meet you, {name}!"

    async def _handle_tell_story(self, device_id: str) -> str:
        state = self._get_state(device_id)
        state.mode = ConversationMode.STORY_LISTEN
        state.story_parts = []
        state.followup_count = 0
        name = state.speaker_name
        if name:
            return f"Go ahead, {name}. I'm listening."
        return "Go ahead, I'm listening."

    async def _handle_hear_stories(self, intent_result: dict, device_id: str = "unknown") -> str:
        state = self._get_state(device_id)
        tid = state.tenant_id
        query = intent_result.get("query")

        _fallback_intro = None  # set if we fall back from a topic miss
        if query:
            # Specific topic/person request — no rotation filter
            stories = self.db.search_stories_by_speaker_or_topic(query, tenant_id=tid)
            if not stories:
                # No match — fall back to a random story with a friendly redirect
                import random as _rnd
                all_stories = self.db.get_stories(tenant_id=tid, limit=50)
                if not all_stories:
                    return f"I don't have any stories about {query} yet. Maybe you could tell me one?"
                stories = all_stories
                _fallback_intros = [
                    f"I don't recall a story about {query}, but let me tell you another one.",
                    f"Hmm, I'm not finding one about {query}. But here's a good one.",
                    f"I don't think I have one about {query} yet, but I've got this.",
                    f"Nothing about {query} comes to mind, but listen to this one.",
                    f"I'm drawing a blank on {query}, but here's a memory I love.",
                    f"I don't have one about {query} right now, but let me share this instead.",
                    f"Let me think... I don't have {query} yet, but how about this one?",
                ]
                _fallback_intro = _rnd.choice(_fallback_intros)
                query = None  # treat as general from here on
        else:
            # General "read me a story" — pull stories, sorted least-recently-narrated first
            all_stories = self.db.get_stories(tenant_id=tid, limit=50)
            if not all_stories:
                return "I don't have any stories recorded yet. Want to tell me one?"

            # Sort by least recently narrated so we always pick the freshest stories
            last_narrated = self.db.get_story_last_narrated(tid)
            stories = sorted(all_stories, key=lambda s: last_narrated.get(s["id"], ""))

        # Check for a kept (cached) narrative — prefer least-recently-used
        if not query:
            try:
                kept_narratives = self.db.get_narratives(tid, status="kept")
                if kept_narratives:
                    last_narrated = self.db.get_story_last_narrated(tid)
                    # Score each kept narrative by how recently its stories were told
                    best_kn = None
                    best_score = None
                    for kn in kept_narratives:
                        kn_ids = [int(x) for x in kn["story_ids"].split(",") if x.strip()] if kn.get("story_ids") else []
                        if not kn_ids:
                            continue
                        # Score = max last-narrated timestamp of its stories (lower = older = better)
                        score = max(last_narrated.get(sid, "") for sid in kn_ids)
                        if best_score is None or score < best_score:
                            best_score = score
                            best_kn = kn
                    if best_kn:
                        kn_ids = [int(x) for x in best_kn["story_ids"].split(",") if x.strip()]
                        self.db.log_narrative_stories(kn_ids, tenant_id=tid, query=query)
                        result = best_kn["narrative"]
                        if best_kn.get("attribution"):
                            result = f"{best_kn['attribution']} {result}"
                        logger.info(f"Using kept narrative #{best_kn['id']}")
                        if _fallback_intro:
                            result = f"{_fallback_intro} {result}"
                        return result
            except Exception as e:
                logger.error(f"Kept narrative lookup error: {e}")

        # Build narrative from stories using OpenAI
        if self.followup_gen and self.followup_gen.available:
            try:
                import asyncio
                narrative, used_ids = await asyncio.to_thread(
                    self._generate_story_narrative, stories, query, tid
                )
                if narrative:
                    # Log which stories were used
                    if used_ids:
                        self.db.log_narrative_stories(used_ids, tenant_id=tid, query=query)

                    # Build attribution intro from story speakers
                    intro = self._build_story_attribution(stories, used_ids, query)

                    # Save narrative as draft for review in dashboard
                    try:
                        self.db.save_narrative(tid, narrative, attribution=intro,
                                               story_ids=used_ids, query=query)
                    except Exception:
                        pass

                    if _fallback_intro:
                        narrative = f"{_fallback_intro} {narrative}"
                    elif intro:
                        narrative = f"{intro} {narrative}"
                    return narrative
            except Exception as e:
                logger.error(f"Story narrative generation error: {e}")

        # Fallback: read back the most relevant story directly
        story = stories[0]
        transcript = story.get("corrected_transcript") or story.get("transcript", "")
        if len(transcript) > 500:
            transcript = transcript[:500] + "..."
        prefix = _fallback_intro if _fallback_intro else "Here's a story that was shared:"
        return f"{prefix} {transcript}"

    def _build_story_attribution(self, stories: list, used_ids: list, query: str = None) -> str:
        """Build a spoken intro like 'This story is from Glen' or 'Here's a story about the lake from Brooklyn'."""
        import random
        # Get unique speaker names from the stories that were actually used
        # Normalize: strip whitespace, deduplicate by first name to avoid
        # "Glen Rogers, Glen and Glen" when the same person has variants
        speakers = []
        seen_first_names = set()
        for s in stories:
            if s["id"] in used_ids and s.get("speaker_name"):
                name = s["speaker_name"].strip()
                if not name:
                    continue
                first_name = name.split()[0].lower()
                if first_name not in seen_first_names:
                    seen_first_names.add(first_name)
                    speakers.append(name)

        if not speakers:
            return ""

        if len(speakers) == 1:
            name = speakers[0]
            if query:
                return random.choice([
                    f"Here's a story about {query} from {name}.",
                    f"This one about {query} comes from {name}.",
                    f"{name} shared this one about {query}.",
                ])
            else:
                return random.choice([
                    f"This story is from {name}.",
                    f"Here's one from {name}.",
                    f"{name} shared this one.",
                    f"This comes from {name}.",
                ])
        else:
            names = ", ".join(speakers[:-1]) + f" and {speakers[-1]}"
            if query:
                return f"Here's a story about {query} from {names}."
            else:
                return random.choice([
                    f"This story comes from {names}.",
                    f"Here's one from {names}.",
                    f"{names} shared these memories.",
                ])

    def _generate_story_narrative(self, stories: list, query: str = None, tenant_id: int = None) -> tuple:
        """Use OpenAI to weave stored stories into a warm narrative.
        Returns (narrative_text, list_of_story_ids_used)."""
        import random
        # Collect story excerpts (cap total to ~3000 chars for prompt)
        excerpts = []
        used_ids = []
        total_len = 0
        for s in stories:
            text = s.get("corrected_transcript") or s.get("transcript", "")
            if not text:
                continue
            if total_len + len(text) > 3000:
                remaining = 3000 - total_len
                if remaining > 200:
                    excerpts.append(text[:remaining])
                    used_ids.append(s["id"])
                break
            excerpts.append(text)
            used_ids.append(s["id"])
            total_len += len(text)

        if not excerpts:
            return None, []

        story_text = "\n\n---\n\n".join(excerpts)
        topic_hint = f" Focus on stories about {query}." if query else ""

        # Vary the narrative style each time
        styles = [
            "Focus on the emotions and feelings in these memories.",
            "Highlight a fun or surprising detail from the stories.",
            "Start with the most vivid moment and work outward.",
            "Connect the stories through the people involved.",
            "Focus on what made these moments special.",
            "Tell it like sharing a favorite memory with a friend.",
            "Highlight the relationships between the people in the stories.",
            "Focus on a small detail that makes the story come alive.",
        ]
        style = random.choice(styles)

        # Check for previous narratives using these same stories so GPT avoids repeating
        avoid_hint = ""
        if tenant_id and used_ids:
            try:
                prev = self.db.get_narratives(tenant_id)
                prev_set = set(used_ids)
                for n in prev[:5]:
                    n_ids = set(int(x) for x in n["story_ids"].split(",") if x.strip()) if n.get("story_ids") else set()
                    if n_ids & prev_set:
                        avoid_hint = f"\n- DO NOT repeat or closely paraphrase this previous version: \"{n['narrative'][:200]}\""
                        break
            except Exception:
                pass

        prompt = f"""You are Polly, a warm companion for an elderly person.
Weave these family stories into ONE short spoken paragraph.

Rules:
- MAXIMUM 3 sentences, 40-60 words total. Never exceed this.
- Warm, conversational tone — like a grandparent reminiscing
- Honor the original words — don't invent new facts
- No quotation marks or "they said"
- One flowing paragraph, not a list
- Style direction: {style}{topic_hint}{avoid_hint}

FAMILY STORIES:
{story_text}

NARRATIVE:"""

        response = self.followup_gen._client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.7,
        )

        narrative = response.choices[0].message.content.strip()
        # Hard cap: truncate to ~80 words to prevent TTS timeout
        words = narrative.split()
        if len(words) > 80:
            # Cut at last sentence boundary within 80 words
            truncated = " ".join(words[:80])
            last_period = truncated.rfind(".")
            if last_period > 20:
                truncated = truncated[:last_period + 1]
            narrative = truncated
        return narrative, used_ids

    def _get_owner_age(self, tenant_id: int) -> Optional[int]:
        """Calculate owner's current age from birth_year in user_profiles."""
        if not tenant_id:
            return None
        try:
            conn = self.db._get_connection()
            row = conn.execute(
                "SELECT birth_year FROM user_profiles WHERE tenant_id = ? AND birth_year IS NOT NULL LIMIT 1",
                (tenant_id,)
            ).fetchone()
            if row and row[0]:
                from datetime import datetime
                return datetime.now().year - row[0]
        except Exception:
            pass
        return None

    async def _handle_family_question(self, device_id: str) -> str:
        state = self._get_state(device_id)

        # Use engagement tracker for smart question selection if available
        if self.engagement:
            question_data = self.engagement.select_question(
                self.data, speaker=state.speaker_name,
                tenant_id=state.tenant_id
            )
        else:
            question_data = self.data.get_family_question()

        if not question_data:
            return "I don't have any family questions ready right now."

        question_text = question_data["question"]
        state.mode = ConversationMode.STORY_PROMPT
        state.current_question = question_text
        state.current_bucket = question_data.get("jungian_stage", "ordinary_world")
        state.current_life_phase = question_data.get("life_phase", "childhood")
        state.critical_thinking_step = 1
        state.story_parts = []
        state.followup_count = 0
        return question_text

    async def _handle_story_progress(self, device_id: str) -> str:
        state = self._get_state(device_id)
        speaker = state.speaker_name

        if self.engagement:
            progress = self.engagement.get_progress_feedback(speaker, tenant_id=state.tenant_id)
            gap = self.engagement.get_gap_report(speaker, tenant_id=state.tenant_id)
            return f"{progress} {gap}"

        if self.narrative_arc:
            return self.narrative_arc.get_progress_summary(speaker, tenant_id=state.tenant_id)

        count = len(self.db.get_memories(speaker=speaker, tenant_id=state.tenant_id))
        if count == 0:
            return "We haven't started collecting stories yet. Ready when you are."
        return f"You've shared {count} memories so far."

    # Common nicknames/terms mapped to relationship values in the family tree
    RELATION_ALIASES = {
        # Parents
        "mom": ["mother"], "momma": ["mother"], "mama": ["mother"], "ma": ["mother"],
        "mommy": ["mother"], "mum": ["mother"], "mummy": ["mother"],
        "dad": ["father"], "daddy": ["father"], "papa": ["father"], "pa": ["father"],
        "pops": ["father"], "pop": ["father"],
        # Grandparents
        "grandma": ["grandmother", "great-grandmother"], "granny": ["grandmother", "great-grandmother"],
        "nana": ["grandmother", "great-grandmother"], "nanna": ["grandmother", "great-grandmother"],
        "memaw": ["grandmother", "great-grandmother"], "me maw": ["grandmother", "great-grandmother"],
        "meemaw": ["grandmother", "great-grandmother"], "mimi": ["grandmother", "great-grandmother"],
        "gram": ["grandmother", "great-grandmother"], "grammy": ["grandmother", "great-grandmother"],
        "grandpa": ["grandfather", "great-grandfather"], "gramps": ["grandfather", "great-grandfather"],
        "grampa": ["grandfather", "great-grandfather"],
        "papaw": ["grandfather", "great-grandfather"], "pawpaw": ["grandfather", "great-grandfather"],
        "pepaw": ["grandfather", "great-grandfather"],
        # Spouse
        "hubby": ["husband"], "wifey": ["wife"],
        # Children
        "my son": ["son"], "my daughter": ["daughter"],
        "my boy": ["son"], "my girl": ["daughter"],
        # Siblings
        "bro": ["brother"], "sis": ["sister"],
        # In-laws
        "mother in law": ["mother-in-law"], "father in law": ["father-in-law"],
        "son in law": ["son-in-law"], "daughter in law": ["daughter-in-law"],
        "brother in law": ["brother-in-law"], "sister in law": ["sister-in-law"],
    }

    async def _handle_who_is(self, name: str, device_id: str) -> str:
        """Look up a person in the family tree by name or relationship."""
        state = self._get_state(device_id)
        tid = state.tenant_id

        # Search family_members table for matching name
        conn = self.db._get_connection()
        try:
            conn.row_factory = __import__('sqlite3').Row
            rows = conn.execute(
                "SELECT name, relation_to_owner FROM family_members WHERE LOWER(name) LIKE ? AND (tenant_id = ? OR tenant_id IS NULL)",
                (f"%{name.lower()}%", tid)
            ).fetchall()
        finally:
            if not self.db._conn:
                conn.close()

        if rows:
            member = rows[0]
            member_name = member["name"]
            relation = member["relation_to_owner"] or "a family member"
            resp = f"{member_name} is your {relation}."
            self._last_response[device_id] = resp
            return resp

        # Check if the name is a relationship alias (mom, dad, grandma, etc.)
        name_lower = name.lower().strip()
        alias_relations = self.RELATION_ALIASES.get(name_lower)
        if not alias_relations:
            # Also try the raw relationship value (e.g., "mother", "father")
            alias_relations = [name_lower]

        conn = self.db._get_connection()
        try:
            conn.row_factory = __import__('sqlite3').Row
            placeholders = ",".join("?" for _ in alias_relations)
            rows = conn.execute(
                f"SELECT name, relation_to_owner FROM family_members WHERE LOWER(relation_to_owner) IN ({placeholders}) AND (tenant_id = ? OR tenant_id IS NULL)",
                (*alias_relations, tid)
            ).fetchall()
        finally:
            if not self.db._conn:
                conn.close()

        if rows:
            if len(rows) == 1:
                member = rows[0]
                member_name = member["name"]
                relation = member["relation_to_owner"] or "a family member"
                resp = f"{member_name} is your {relation}."
            else:
                # Multiple matches (e.g., "who is grandma" with two grandmothers)
                parts = []
                for member in rows:
                    parts.append(f"{member['name']} ({member['relation_to_owner']})")
                resp = f"You have {len(rows)}: {', '.join(parts)}."
            self._last_response[device_id] = resp
            return resp

        # Check family identity service for visitors
        if self.family_identity:
            member_info = self.family_identity.recognize_member(name, tenant_id=tid)
            if member_info:
                member_name = member_info.get("name", name)
                relationship = member_info.get("relationship", "")
                if relationship:
                    resp = f"{member_name} is {relationship}."
                else:
                    resp = f"I know {member_name}, but I don't have details about them."
                self._last_response[device_id] = resp
                return resp

        return f"I don't know who {name} is. You can add them to the family tree on the web portal."

    @staticmethod
    def _natural_status(status: str) -> str:
        """Make a status phrase sound natural with proper prepositions.
        'going to the store' → 'going to the store' (already has verb)
        'the store' → 'at the store' (bare location needs preposition)
        'at the store' → 'at the store' (already has preposition)
        """
        s = status.strip()
        if not s:
            return "out"
        # Already starts with an action verb — sounds natural as-is
        action_starts = (
            "going", "headed", "heading", "leaving", "running",
            "off to", "on the way", "driving", "walking", "picking up",
            "at ", "in ", "on ", "out ",
        )
        if any(s.lower().startswith(a) for a in action_starts):
            return s
        # Bare location — add "at"
        return f"at {s}"

    def _ends_with_termination(self, text: str) -> bool:
        """Check if text ENDS with a termination phrase (not in the middle)."""
        import re
        return bool(re.search(
            r"(i'?m done|goodbye|bye bye|bye|that'?s enough|i'?m tired|"
            r"let'?s stop|no more|enough for today|see you later|good night)"
            r"[\s,.!?]*$",
            text.lower()
        ))

    def _strip_termination_phrases(self, text: str) -> str:
        """Remove 'I'm done', 'goodbye', etc. from the end of text."""
        import re
        cleaned = text
        # Iteratively strip termination phrases from the end (handles repeated ones)
        for _ in range(4):
            cleaned = re.sub(
                r"[\s,.]*(i'?m done|goodbye|bye bye|bye|that'?s enough|i'?m tired|"
                r"let'?s stop|no more|enough for today|stop|see you later|good night)[\s,.!?]*$",
                "", cleaned, flags=re.IGNORECASE
            ).strip()
        return cleaned

    # ── Conversation-aware processing ──

    async def process_in_context(self, intent_result: dict, raw_text: str,
                                 device_id: str = "unknown") -> Tuple[str, ConversationMode]:
        """
        Context-aware wrapper around process().
        When in a conversational mode (STORY_PROMPT, FOLLOWUP_WAIT, STORY_LISTEN),
        treats incoming text as an answer rather than parsing it as a new intent.
        Returns (response_text, new_mode).
        """
        state = self._get_state(device_id)
        tid = state.tenant_id

        # If in COMMAND mode, use normal intent processing
        if state.mode == ConversationMode.COMMAND:
            response = await self.process(intent_result, raw_text, device_id)
            return (response, state.mode)

        # Check for explicit stop/exit commands even in conversational mode
        intent = intent_result.get("intent", "unknown")

        # Also catch "I'm done" / "that's enough" directly from text
        # (intent parser may misclassify these)
        if intent not in ("stop", "goodbye") and self._ends_with_termination(raw_text):
            intent = "goodbye"

        if intent in ("stop", "goodbye"):
            # Only exit if the termination phrase is at the END of what they said.
            # "I'm done working at the factory" → NOT a stop, it's part of the story.
            # "...and that's my story. I'm done" → IS a stop.
            if not self._ends_with_termination(raw_text):
                logger.info(f"Termination phrase mid-sentence, treating as story answer: {raw_text[:80]}")
                # Fall through to story answer processing below
            else:
                # Save any story answer embedded before the termination phrase
                saved_story = False
                if state.mode in (ConversationMode.STORY_PROMPT, ConversationMode.FOLLOWUP_WAIT,
                                  ConversationMode.STORY_LISTEN):
                    clean_text = self._strip_termination_phrases(raw_text)
                    if clean_text and len(clean_text) > 20:
                        state.story_parts.append(clean_text)
                        story_id = self.db.save_story(
                            transcript=clean_text,
                            speaker_name=state.speaker_name,
                            source="family_story",
                            tenant_id=tid,
                            question_text=state.current_question,
                        )
                        # Auto-tag story
                        try:
                            self.db.auto_tag_story(story_id, clean_text, tenant_id=tid)
                        except Exception:
                            pass
                        if self.memory_extractor:
                            mem_data = self.memory_extractor.extract(
                                text=clean_text,
                                question=state.current_question,
                                speaker=state.speaker_name,
                                bucket_hint=state.current_bucket,
                            )
                            fingerprint = self.memory_extractor.compute_fingerprint(mem_data)
                            self.db.save_memory(
                                story_id=story_id,
                                speaker=state.speaker_name,
                                bucket=mem_data["bucket"],
                                life_phase=mem_data["life_phase"],
                                text_summary=mem_data["text_summary"],
                                text=clean_text,
                                people=mem_data["people"],
                                locations=mem_data["locations"],
                                emotions=mem_data["emotions"],
                                fingerprint=fingerprint,
                                tenant_id=tid,
                            )
                        saved_story = True
                        logger.info(f"Saved story answer before goodbye ({len(clean_text)} chars)")

                name = state.speaker_name
                state.reset()
                if saved_story:
                    if name:
                        return (f"Thank you for sharing that, {name}. Goodbye for now, I'll be here when you want to talk again.", ConversationMode.COMMAND)
                    return ("Thank you for sharing. Goodbye for now, I'll be here when you want to talk again.", ConversationMode.COMMAND)
                response = await self.process(intent_result, raw_text, device_id)
                return (response, ConversationMode.COMMAND)

        # Handle thinking — user needs more time
        # But if the answer is long (>80 chars), it's a real story answer that
        # happens to contain a trigger word like "wait" or "i don't know"
        is_story_mode = state.mode in (ConversationMode.STORY_PROMPT, ConversationMode.FOLLOWUP_WAIT)
        is_long_answer = len(raw_text.strip()) > 80

        if intent == "thinking" and not (is_story_mode and is_long_answer):
            return ("Take your time. Continue when you're ready, and say 'I'm done' when you're finished.", state.mode)

        # Handle repeat — re-ask the current question
        if intent == "repeat" and state.current_question:
            return (f"Sure, no problem. {state.current_question}", state.mode)

        # Handle skip — move to a new question
        if intent == "skip" and not (is_story_mode and is_long_answer):
            if state.mode in (ConversationMode.STORY_PROMPT, ConversationMode.FOLLOWUP_WAIT):
                response = await self._handle_family_question(device_id)
                return (f"No problem, let's try another one. {response}", state.mode)

        # In AWAITING_NAME mode — save name for pending status message
        if state.mode == ConversationMode.AWAITING_NAME:
            return await self._process_name_answer(raw_text, device_id)

        # In AWAITING_RELATIONSHIP mode — save the relationship answer
        if state.mode == ConversationMode.AWAITING_RELATIONSHIP:
            return await self._process_relationship_answer(raw_text, device_id)

        # In conversational mode — treat raw_text as an answer
        if state.mode in (ConversationMode.STORY_PROMPT, ConversationMode.FOLLOWUP_WAIT):
            return await self._process_story_answer(raw_text, device_id)

        if state.mode == ConversationMode.STORY_LISTEN:
            return await self._process_story_listen(raw_text, device_id)

        # Fallback
        response = await self.process(intent_result, raw_text, device_id)
        return (response, state.mode)

    async def _process_name_answer(self, raw_text: str,
                                     device_id: str) -> Tuple[str, ConversationMode]:
        """Process name answer for pending status update."""
        import re
        state = self._get_state(device_id)
        tid = state.tenant_id

        # Clean up: strip wake phrases, filler words
        cleaned = re.sub(r'\b(hey|hi|hello|polly|um|uh|this is|my name is|i\'?m)\b',
                         '', raw_text.lower()).strip()
        # Take the first remaining word as the name
        words = cleaned.split()
        name = words[0].title() if words else None

        if not name:
            return ("I didn't catch your name. Who is this?", ConversationMode.AWAITING_NAME)

        status_text = state.pending_status
        state.speaker_name = name
        state.pending_status = None
        state.mode = ConversationMode.COMMAND

        if status_text:
            self.db.save_message(from_name=name, message=status_text, tenant_id=tid)
            msg = self._natural_status(status_text)
            return (f"Got it, {name}. I'll post to the board that you're {msg}.",
                    ConversationMode.COMMAND)

        return (f"Hi {name}! What can I do for you?", ConversationMode.COMMAND)

    async def _process_relationship_answer(self, raw_text: str,
                                            device_id: str) -> Tuple[str, ConversationMode]:
        """Process the user's answer about how they know the owner."""
        state = self._get_state(device_id)
        name = state.speaker_name

        if not raw_text or not raw_text.strip():
            return ("I didn't catch that. How do you know the family?", ConversationMode.AWAITING_RELATIONSHIP)

        # Save the relationship
        relationship = raw_text.strip()
        if self.family_identity:
            self.family_identity.update_relationship(name, relationship, tenant_id=state.tenant_id)

        state.mode = ConversationMode.COMMAND
        return (f"Wonderful! I'll remember you're {relationship}. It's great to meet you, {name}!",
                ConversationMode.COMMAND)

    async def _process_story_answer(self, answer_text: str,
                                    device_id: str) -> Tuple[str, ConversationMode]:
        """Process an answer given during STORY_PROMPT or FOLLOWUP_WAIT mode."""
        state = self._get_state(device_id)
        tid = state.tenant_id

        if not answer_text or not answer_text.strip():
            return ("Take your time. I'm listening.", state.mode)

        # Check subscription limits before saving
        from core.subscription import check_feature
        if not check_feature(self.db, tid, "add_story"):
            state.reset()
            return ("I'd love to save that story, but your plan limit has been reached. "
                    "Visit the Polly website to upgrade and keep recording.",
                    ConversationMode.COMMAND)

        # Save the answer as a story part
        state.story_parts.append(answer_text)

        # Save raw story to DB (with WAV if available)
        wav_filename = getattr(state, '_pending_wav', None)
        story_id = self.db.save_story(
            transcript=answer_text,
            audio_s3_key=wav_filename,
            speaker_name=state.speaker_name,
            source="family_story",
            tenant_id=tid,
            question_text=state.current_question,
        )
        if wav_filename:
            state._pending_wav = None
            logger.info(f"Story #{story_id} saved with audio: {wav_filename}")
        # Auto-tag story
        try:
            self.db.auto_tag_story(story_id, answer_text, tenant_id=tid)
        except Exception:
            pass

        # Extract structured memory and save
        if self.memory_extractor:
            mem_data = self.memory_extractor.extract(
                text=answer_text,
                question=state.current_question,
                speaker=state.speaker_name,
                bucket_hint=state.current_bucket,
            )
            fingerprint = self.memory_extractor.compute_fingerprint(mem_data)
            self.db.save_memory(
                story_id=story_id,
                speaker=state.speaker_name,
                bucket=mem_data["bucket"],
                life_phase=mem_data["life_phase"],
                text_summary=mem_data["text_summary"],
                text=answer_text,
                people=mem_data["people"],
                locations=mem_data["locations"],
                emotions=mem_data["emotions"],
                fingerprint=fingerprint,
                tenant_id=tid,
            )
            # Update state with detected context
            if not state.current_bucket:
                state.current_bucket = mem_data["bucket"]
            if not state.current_life_phase:
                state.current_life_phase = mem_data["life_phase"]

        # Story saved — thank the user and return to command mode.
        # No follow-up loop. If they want another question, they say "ask me a question" again.
        if self.echo_engine:
            closing = self.echo_engine.generate_closing(state.speaker_name)
        else:
            name_part = f", {state.speaker_name}" if state.speaker_name else ""
            closing = f"That was a wonderful story. Thank you for sharing{name_part}."
        # No follow-up prompt — clean ending
        state.reset()
        return (closing, ConversationMode.COMMAND)

    async def _process_story_listen(self, transcript: str,
                                    device_id: str) -> Tuple[str, ConversationMode]:
        """Process transcript during STORY_LISTEN mode (free-form storytelling)."""
        state = self._get_state(device_id)
        tid = state.tenant_id

        if not transcript or not transcript.strip():
            return ("I'm still listening whenever you're ready.", state.mode)

        state.story_parts.append(transcript)

        # Save raw story (with WAV if available)
        wav_filename = getattr(state, '_pending_wav', None)
        story_id = self.db.save_story(
            transcript=transcript,
            audio_s3_key=wav_filename,
            speaker_name=state.speaker_name,
            source="family_story",
            tenant_id=tid,
        )
        if wav_filename:
            state._pending_wav = None
            logger.info(f"Story #{story_id} saved with audio: {wav_filename}")
        # Auto-tag story
        try:
            self.db.auto_tag_story(story_id, transcript, tenant_id=tid)
        except Exception:
            pass

        # Extract and save structured memory
        if self.memory_extractor:
            mem_data = self.memory_extractor.extract(
                text=transcript,
                speaker=state.speaker_name,
            )
            fingerprint = self.memory_extractor.compute_fingerprint(mem_data)
            self.db.save_memory(
                story_id=story_id,
                speaker=state.speaker_name,
                bucket=mem_data["bucket"],
                life_phase=mem_data["life_phase"],
                text_summary=mem_data["text_summary"],
                text=transcript,
                people=mem_data["people"],
                locations=mem_data["locations"],
                emotions=mem_data["emotions"],
                fingerprint=fingerprint,
                tenant_id=tid,
            )
            state.current_bucket = mem_data["bucket"]

        state.followup_count += 1
        state.critical_thinking_step = min(state.critical_thinking_step + 1, 6)

        if state.followup_count >= state.max_followups:
            if self.echo_engine:
                closing = self.echo_engine.generate_closing(state.speaker_name)
            else:
                closing = "That was a wonderful story. Thank you for sharing."
            state.reset()
            return (closing, ConversationMode.COMMAND)

        # Generate arc-aware follow-up
        if self.echo_engine:
            followup = await self.echo_engine.generate_followup(
                "Tell me more", transcript, state.followup_count,
                bucket=state.current_bucket,
                critical_thinking_step=state.critical_thinking_step,
            )
            state.current_question = followup
            state.mode = ConversationMode.FOLLOWUP_WAIT
            return (followup, ConversationMode.FOLLOWUP_WAIT)

        state.reset()
        return ("Thank you for sharing that story.", ConversationMode.COMMAND)
