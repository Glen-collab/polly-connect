"""
Central command processor for Polly Connect.
Handles all intents with access to all services.
Tracks last_response per device for "repeat" functionality.
"""

import logging
from typing import Optional, Tuple

from core.conversation_state import ConversationMode, ConversationState

logger = logging.getLogger(__name__)


class CommandProcessor:
    """
    Central handler for all voice intents.
    Initialized with all service instances, called from audio.py.
    """

    def __init__(self, db, data, bible_service=None, weather_service=None,
                 med_scheduler=None, family_identity=None, echo_engine=None,
                 memory_extractor=None, narrative_arc=None,
                 engagement=None):
        self.db = db
        self.data = data
        self.bible = bible_service
        self.weather = weather_service
        self.meds = med_scheduler
        self.family_identity = family_identity
        self.echo_engine = echo_engine
        self.memory_extractor = memory_extractor
        self.narrative_arc = narrative_arc
        self.engagement = engagement
        self._last_response = {}
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

        # ── Family storytelling ──

        elif intent == "introduce_self":
            return await self._handle_introduce(intent_result, device_id)

        elif intent == "tell_story":
            return await self._handle_tell_story(device_id)

        elif intent == "hear_stories":
            return await self._handle_hear_stories(intent_result)

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

        if self.family_identity:
            member = self.family_identity.register_member(name, relationship)
            visit_count = member.get("visit_count", 1)
            state = self._get_state(device_id)
            state.speaker_name = name
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

    async def _handle_hear_stories(self, intent_result: dict) -> str:
        query = intent_result.get("query")
        if not query:
            return "Who would you like to hear stories about?"
        stories = self.db.search_stories_by_speaker_or_topic(query)
        if not stories:
            return f"I don't have any stories about {query} yet. Maybe you could tell me one?"
        story = stories[0]
        speaker = story.get("speaker_name") or "someone"
        transcript = story.get("transcript", "")
        if len(transcript) > 300:
            transcript = transcript[:300] + "..."
        return f"Here's something {speaker} shared: {transcript}"

    async def _handle_family_question(self, device_id: str) -> str:
        state = self._get_state(device_id)

        # Use engagement tracker for smart question selection if available
        if self.engagement:
            question_data = self.engagement.select_question(
                self.data, speaker=state.speaker_name
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
            progress = self.engagement.get_progress_feedback(speaker)
            gap = self.engagement.get_gap_report(speaker)
            return f"{progress} {gap}"

        if self.narrative_arc:
            return self.narrative_arc.get_progress_summary(speaker)

        count = len(self.db.get_memories(speaker=speaker))
        if count == 0:
            return "We haven't started collecting stories yet. Ready when you are."
        return f"You've shared {count} memories so far."

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

        # If in COMMAND mode, use normal intent processing
        if state.mode == ConversationMode.COMMAND:
            response = await self.process(intent_result, raw_text, device_id)
            return (response, state.mode)

        # Check for explicit stop/exit commands even in conversational mode
        intent = intent_result.get("intent", "unknown")
        if intent in ("stop", "goodbye"):
            state.reset()
            response = await self.process(intent_result, raw_text, device_id)
            return (response, ConversationMode.COMMAND)

        # Handle thinking — user needs more time
        if intent == "thinking":
            return ("Take your time. Continue when you're ready, and say 'I'm done' when you're finished.", state.mode)

        # Handle repeat — re-ask the current question
        if intent == "repeat" and state.current_question:
            return (f"Sure, no problem. {state.current_question}", state.mode)

        # Handle skip — move to a new question
        if intent == "skip":
            if state.mode in (ConversationMode.STORY_PROMPT, ConversationMode.FOLLOWUP_WAIT):
                response = await self._handle_family_question(device_id)
                return (f"No problem, let's try another one. {response}", state.mode)

        # In conversational mode — treat raw_text as an answer
        if state.mode in (ConversationMode.STORY_PROMPT, ConversationMode.FOLLOWUP_WAIT):
            return await self._process_story_answer(raw_text, device_id)

        if state.mode == ConversationMode.STORY_LISTEN:
            return await self._process_story_listen(raw_text, device_id)

        # Fallback
        response = await self.process(intent_result, raw_text, device_id)
        return (response, state.mode)

    async def _process_story_answer(self, answer_text: str,
                                    device_id: str) -> Tuple[str, ConversationMode]:
        """Process an answer given during STORY_PROMPT or FOLLOWUP_WAIT mode."""
        state = self._get_state(device_id)

        if not answer_text or not answer_text.strip():
            return ("Take your time. I'm listening.", state.mode)

        # Save the answer as a story part
        state.story_parts.append(answer_text)

        # Save raw story to DB
        story_id = self.db.save_story(
            transcript=answer_text,
            speaker_name=state.speaker_name,
            source="family_story",
        )

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
            )
            # Update state with detected context
            if not state.current_bucket:
                state.current_bucket = mem_data["bucket"]
            if not state.current_life_phase:
                state.current_life_phase = mem_data["life_phase"]

        state.followup_count += 1
        state.critical_thinking_step = min(state.critical_thinking_step + 1, 6)

        # Check if we've reached max follow-ups
        if state.followup_count >= state.max_followups:
            if self.echo_engine:
                closing = self.echo_engine.generate_closing(state.speaker_name)
            else:
                name_part = f", {state.speaker_name}" if state.speaker_name else ""
                closing = f"That was a wonderful story. Thank you for sharing{name_part}."
            state.reset()
            return (closing, ConversationMode.COMMAND)

        # Generate ECHO-BRIDGE-INVITE follow-up (now arc-aware)
        if self.echo_engine:
            question = state.current_question or ""
            followup = await self.echo_engine.generate_followup(
                question, answer_text, state.followup_count,
                bucket=state.current_bucket,
                critical_thinking_step=state.critical_thinking_step,
            )
            state.current_question = followup
            state.mode = ConversationMode.FOLLOWUP_WAIT
            return (followup, ConversationMode.FOLLOWUP_WAIT)

        # No echo engine — just thank them and return to command mode
        state.reset()
        return ("Thank you for sharing that.", ConversationMode.COMMAND)

    async def _process_story_listen(self, transcript: str,
                                    device_id: str) -> Tuple[str, ConversationMode]:
        """Process transcript during STORY_LISTEN mode (free-form storytelling)."""
        state = self._get_state(device_id)

        if not transcript or not transcript.strip():
            return ("I'm still listening whenever you're ready.", state.mode)

        state.story_parts.append(transcript)

        # Save raw story
        story_id = self.db.save_story(
            transcript=transcript,
            speaker_name=state.speaker_name,
            source="family_story",
        )

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
