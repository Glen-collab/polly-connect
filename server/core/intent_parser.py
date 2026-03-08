"""
Intent Parser for Polly Connect
"""

import re
from typing import Dict, Optional


class IntentParser:
    def __init__(self, use_spacy: bool = False):
        self.use_spacy = False  # Disabled for simplicity
        self._family_names = set()  # populated from family tree

        # Family storytelling intents
        self._introduce_self_phrases = [
            "this is ", "my name is ", "i'm ",
        ]
        self._tell_story_phrases = [
            "let me tell you about", "i remember when", "i want to tell you",
            "let me share", "i have a story", "tell me a story",
            "i want to share", "record my story", "take my story",
            "story time", "i want to record", "i have something to share",
            "i want to tell a story", "let me tell you something",
            "can i tell you something", "i got a story",
            "i have a memory to share", "can i share a story",
        ]
        self._hear_stories_phrases = [
            "tell me about", "what did", "play back",
            "what stories", "any stories about", "what has",
            "read me a story", "play a story", "do you have any stories",
            "what have you heard about",
        ]
        self._family_question_phrases = [
            "ask me about my family", "family question", "ask me a family question",
            "family story", "ask me something about my life",
            "ask me about my life", "tell me about my family",
            "ask me a question about my life",
            "i want to answer questions", "interview me",
            "let's do a family question", "give me a question",
            "ask me about my past", "ask me about growing up",
        ]
        self._story_progress_phrases = [
            "how many stories", "my progress", "how are we doing",
            "story progress", "how many memories", "show my progress",
            "what have we captured", "book progress",
            "how's the book coming", "how's my book",
            "how far along are we", "how many have we done",
        ]

        self.container_words = {
            "drawer", "bin", "box", "shelf", "cabinet", "toolbox", "container",
            "bucket", "tray", "rack", "pegboard", "wall", "corner", "workbench",
            "bench", "table", "floor", "hook", "hanger", "bag", "case"
        }

        # Trigger phrases for non-memory intents (from polly-config)
        self._tell_kid_joke_phrases = [
            "tell me a kid joke", "tell me a kids joke", "kid joke",
            "tell me a potty joke", "potty joke", "tell me a poop joke",
            "poop joke", "fart joke", "tell me a fart joke",
            "tell me a silly joke", "silly joke",
            "tell me a funny kid joke", "tell me a gross joke",
            "tell me a unicorn joke", "unicorn joke",
            "tell me a dinosaur joke", "dinosaur joke",
            "tell the kids a joke", "joke for kids",
            "joke for the kids", "got a kid joke",
            "do you know any kid jokes", "say a funny joke for kids",
            "kids joke", "tell us a kid joke",
            "tell a kid joke", "got any kid jokes",
        ]
        self._tell_joke_phrases = [
            "tell me a joke", "make me laugh", "say something funny",
            "i need a laugh", "cheer me up", "tell a joke",
            "got any jokes", "do you know any jokes", "know any jokes",
            "give me a joke", "hit me with a joke", "another joke",
            "tell me another joke", "tell me another one",
            "one more joke", "got another joke", "joke please",
            "can you tell me a joke", "do you have any jokes",
            "let's hear a joke", "how about a joke",
        ]
        self._ask_question_phrases = [
            "ask me a question", "let's talk",
            "got any questions for me", "what do you want to know",
            "i'm ready for a question", "go ahead and ask me",
            "let's do a question", "question time",
        ]
        self._repeat_phrases = [
            "repeat", "say that again", "what did you say", "what was that",
            "pardon", "come again", "one more time",
            "can you repeat that", "i didn't hear you", "i didn't catch that",
            "ask me again", "ask me that again", "ask that again",
            "what was the question", "what did you ask", "say it again",
            "can you ask me again", "ask that question again",
            "huh", "excuse me", "i missed that", "sorry what",
            "can you say that again", "repeat that please",
            "tell me again", "run that by me again",
        ]
        self._slower_phrases = [
            "slower", "slow down", "talk slower", "speak slower",
            "too fast", "not so fast", "can you slow down",
            "you're talking too fast", "that was too fast",
            "speak more slowly", "take it slow",
        ]
        self._thinking_phrases = [
            "i'm still thinking", "still thinking", "hang on",
            "let me think", "hold on", "hold your horses",
            "wait a minute", "give me a second", "give me a moment",
            "this is deep", "that's a good question", "good question",
            "let me see", "hmm", "um", "one second", "one moment",
            "i'm thinking", "thinking", "wait", "just a moment",
            "i need a minute", "hold that thought",
        ]
        self._skip_phrases = [
            "skip", "next question", "skip this one", "i don't know",
            "pass", "next one", "move on",
            "skip that", "i'll skip that one", "give me a different one",
            "try another one", "different question", "ask me something else",
            "i don't want to answer that", "i'd rather not",
        ]
        self._stop_phrases = [
            "stop", "that's enough", "i'm tired", "let's stop",
            "no more", "i'm done", "enough for today",
            "i'm finished", "we're done", "that's all",
            "that's it", "let's be done", "all done",
            "i'm all done", "no more questions",
            "that's all for now", "we can stop",
        ]
        self._goodbye_phrases = [
            "goodbye polly", "bye polly", "goodbye", "bye bye",
            "see you later", "good night", "goodnight",
            "goodnight polly", "nighty night", "see you tomorrow",
            "see ya", "bye", "later polly", "talk to you later",
            "i'm going to bed", "going to sleep",
        ]
        self._greeting_phrases = [
            "hello polly", "hi polly", "hey polly", "good morning",
            "good afternoon", "good evening", "hello", "hi there",
            "good morning polly", "morning polly", "morning",
            "hey there", "howdy", "what's up polly",
            "how are you polly", "how are you doing",
        ]
        self._bible_phrases = [
            "read me a verse", "bible verse", "today's verse",
            "give me a verse", "read me today's verse",
            "verse about", "scripture", "read me a psalm",
            "psalm", "read me a proverb", "proverb",
            "read me from the bible", "daily verse",
            "read me some scripture", "what does the bible say",
            "i need a bible verse", "give me some scripture",
            "read from the bible", "do you have a verse",
            "can you read me a verse", "what's today's verse",
            "inspirational verse", "devotional",
        ]
        self._medication_phrases = [
            "remind me to take", "medication", "my pills",
            "what medications", "did i take my pills", "medicine",
            "med reminder", "what pills do i take", "my meds",
            "what are my meds", "when do i take my pills",
            "when is my next pill", "pill schedule",
            "did i take my meds", "have i taken my medicine",
            "i took my pills", "i took my meds", "meds taken",
            "i already took my medicine", "took my medication",
            "what medicine do i take",
        ]
        # Message board intents
        self._check_messages_phrases = [
            "any messages", "check messages", "do i have messages",
            "are there any messages", "messages for me", "check the board",
            "what's on the board", "message board", "what are my messages",
            "read my messages", "read me my messages", "do i have any messages",
            "what messages do i have", "any new messages", "read the messages",
            "what did i miss", "anything on the board",
        ]
        self._clear_messages_phrases = [
            "clear the board", "clear messages", "clear the message board",
            "delete messages", "erase the board", "wipe the board",
            "delete all messages", "clear all messages", "remove all messages",
            "get rid of the messages", "erase messages", "wipe messages",
            "clean the board", "empty the board",
        ]
        self._person_status_words = {
            "dad", "mom", "daddy", "mommy", "papa", "mama",
            "grandma", "grandpa", "brother", "sister",
            "nana", "nanny", "pops", "poppy", "granny",
            "auntie", "aunt", "uncle", "cousin",
            "hubby", "husband", "wife", "wifey",
        }

        self._weather_phrases = [
            "what's the weather", "what is the weather", "weather this week",
            "weather today", "farmer's almanac", "forecast",
            "how's the weather", "what's it like outside",
            "is it going to rain", "what's the forecast",
            "what's the weather like", "weather report",
            "do i need an umbrella", "is it cold outside",
            "what's it going to be like this week",
        ]

        self._time_phrases = [
            "what time is it", "what's the time", "what is the time",
            "do you have the time", "tell me the time", "current time",
            "what time do you have", "can you tell me the time",
            "you got the time", "what time you got",
        ]
        self._date_phrases = [
            "what day is it", "what's today's date", "what is today's date",
            "what's the date", "what is the date", "what day is today",
            "what is today", "what's today", "today's date",
            "what day of the week is it", "what month is it",
            "what year is it", "what's the date today",
            "can you tell me the date", "do you know what day it is",
        ]
        self._thank_you_phrases = [
            "thank you", "thanks polly", "thanks", "thank you polly",
            "appreciate it", "that was helpful", "you're the best",
            "thanks so much", "thank you so much",
            "that's very kind", "you're sweet", "you're so helpful",
            "i appreciate that", "thanks a lot", "thanks a bunch",
            "that was great", "perfect thank you", "awesome thanks",
            "great job polly", "good job polly", "nice one polly",
        ]
        self._who_is_phrases = [
            "who is", "who's",
        ]

    def parse(self, text: str) -> Dict:
        text = text.strip()
        if not text:
            return {"intent": "unknown", "confidence": 0.0}

        text_lower = text.lower()

        # ── Family storytelling intents (check first, order matters) ──

        if self._matches(text_lower, self._story_progress_phrases):
            return {"intent": "story_progress", "confidence": 0.95}

        if self._matches(text_lower, self._family_question_phrases):
            return {"intent": "family_question", "confidence": 0.95}

        if self._matches(text_lower, self._hear_stories_phrases):
            # Extract who they want to hear about
            query = None
            for phrase in ["tell me about", "what did", "any stories about", "what has"]:
                if phrase in text_lower:
                    idx = text_lower.index(phrase) + len(phrase)
                    query = text_lower[idx:].strip().rstrip("?. ")
                    break
            return {"intent": "hear_stories", "query": query, "confidence": 0.9}

        if self._matches(text_lower, self._tell_story_phrases):
            return {"intent": "tell_story", "confidence": 0.95}

        intro = self._parse_introduction(text)
        if intro:
            return {"intent": "introduce_self", "name": intro[0],
                    "relationship": intro[1], "confidence": 0.9}

        # Check non-memory intents (they're simpler/faster)
        if self._matches(text_lower, self._tell_kid_joke_phrases):
            return {"intent": "tell_kid_joke", "confidence": 0.95}

        if self._matches(text_lower, self._tell_joke_phrases):
            return {"intent": "tell_joke", "confidence": 0.95}

        if self._matches(text_lower, self._ask_question_phrases):
            return {"intent": "ask_question", "confidence": 0.95}

        if self._matches(text_lower, self._repeat_phrases):
            return {"intent": "repeat", "confidence": 0.95}

        if self._matches(text_lower, self._slower_phrases):
            return {"intent": "slower", "confidence": 0.95}

        # ── Message board intents (before item queries) ──

        if self._matches(text_lower, self._check_messages_phrases):
            return {"intent": "check_messages", "confidence": 0.95}

        if self._matches(text_lower, self._clear_messages_phrases):
            return {"intent": "clear_messages", "confidence": 0.95}

        # "[person] is home/back" — clear their status
        home_match = re.search(r"(\w+) is (?:home|back|here)\b", text_lower)
        if home_match:
            person = home_match.group(1).strip()
            if person.lower() not in ("it", "this", "that", "there", "what", "who", "everyone"):
                return {"intent": "person_home", "person": person, "confidence": 0.9}

        leave_msg = self._is_leave_message(text_lower)
        if leave_msg:
            return {"intent": "leave_message", "person": leave_msg["person"],
                    "message": leave_msg["message"], "confidence": 0.9}

        person_query = self._is_person_query(text_lower, self._family_names)
        if person_query:
            return {"intent": "where_is_person", "person": person_query, "confidence": 0.9}

        status_update = self._is_status_update(text_lower)
        if status_update:
            return {"intent": "status_update", "person": status_update["person"],
                    "status": status_update["status"], "confidence": 0.85}

        # ── Content intents (before memory/item to avoid false matches) ──

        if self._matches(text_lower, self._bible_phrases):
            topic = None
            topic_match = re.search(r"verse about (.+)", text_lower)
            if topic_match:
                topic = topic_match.group(1).strip()
            elif "psalm" in text_lower:
                topic = "Psalm"
            elif "proverb" in text_lower:
                topic = "Proverb"
            return {"intent": "bible_verse", "topic": topic, "confidence": 0.9}

        if self._matches(text_lower, self._medication_phrases):
            return {"intent": "medication", "confidence": 0.9, "raw": text}

        if self._matches(text_lower, self._weather_phrases):
            return {"intent": "weather", "confidence": 0.9}

        if self._matches(text_lower, self._time_phrases):
            return {"intent": "tell_time", "confidence": 0.95}

        if self._matches(text_lower, self._date_phrases):
            return {"intent": "tell_date", "confidence": 0.95}

        if self._matches(text_lower, self._thank_you_phrases):
            return {"intent": "thank_you", "confidence": 0.9}

        # "Who is [name]?" — extract the name
        who_match = re.search(r"(?:who(?:'s| is) )(.+?)(?:\?|$)", text_lower)
        if who_match:
            name = who_match.group(1).strip()
            if name and name not in ("this", "that", "it", "there", "here"):
                return {"intent": "who_is", "name": name, "confidence": 0.9}

        # ── Memory/item intents ──
        if self._is_help(text_lower):
            return {"intent": "help", "confidence": 1.0}

        if self._is_list(text_lower):
            return {"intent": "list_all", "confidence": 1.0}

        delete_match = self._is_delete(text_lower)
        if delete_match:
            return {"intent": "delete", "item": delete_match, "confidence": 0.9}

        location_query = self._is_location_query(text_lower)
        if location_query:
            return {"intent": "retrieve_location", "location": location_query, "confidence": 0.9}

        item_query = self._is_item_query(text_lower)
        if item_query:
            return {"intent": "retrieve_item", "item": item_query, "confidence": 0.9}

        store_result = self._is_store(text_lower)
        if store_result:
            return {
                "intent": "store",
                "item": store_result["item"],
                "location": store_result["location"],
                "context": store_result.get("context"),
                "confidence": 0.85
            }

        if self._matches(text_lower, self._thinking_phrases):
            return {"intent": "thinking", "confidence": 0.95}

        if self._matches(text_lower, self._skip_phrases):
            return {"intent": "skip", "confidence": 0.95}

        if self._matches(text_lower, self._goodbye_phrases):
            return {"intent": "goodbye", "confidence": 0.95}

        if self._matches(text_lower, self._stop_phrases):
            return {"intent": "stop", "confidence": 0.95}

        if self._matches(text_lower, self._greeting_phrases):
            return {"intent": "greeting", "confidence": 0.9}

        return {"intent": "unknown", "confidence": 0.0}

    def _matches(self, text: str, phrases: list) -> bool:
        """Check if text contains any of the trigger phrases (word-boundary safe)."""
        for phrase in phrases:
            if len(phrase) <= 3:
                # Short words like "um", "hmm" need word boundaries to avoid matching inside words
                if re.search(r'\b' + re.escape(phrase) + r'\b', text):
                    return True
            else:
                if phrase in text:
                    return True
        return False

    def _is_help(self, text: str) -> bool:
        patterns = [
            r"\bhelp\b", r"\bwhat can you do\b", r"\bhow do (i|you)\b",
            r"\bwhat do you do\b", r"\bwhat are you\b",
            r"\bwhat can i (ask|say|do)\b", r"\bwhat are your commands\b",
            r"\bwhat else can you do\b", r"\bwhat are you capable of\b",
            r"\bi need help\b", r"\bcan you help me\b",
        ]
        return any(re.search(p, text) for p in patterns)

    def _is_list(self, text: str) -> bool:
        patterns = [
            r"\blist (all|everything)\b",
            r"\bshow (all|everything)\b",
            r"\bwhat do you (know|remember)\b"
        ]
        return any(re.search(p, text) for p in patterns)

    def _is_delete(self, text: str) -> Optional[str]:
        patterns = [
            r"(?:forget|remove|delete)(?: about)? (?:the |my )?(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return None

    def _is_location_query(self, text: str) -> Optional[str]:
        patterns = [
            r"what(?:'s| is| do i have) (?:in|on|at|under|behind) (?:the |my )?(.+?)(?:\?|$)",
            r"what(?:'s| is) (?:stored |kept )?(?:in|on|at|under|behind) (?:the |my )?(.+?)(?:\?|$)",
            r"show me (?:the |my )?(.+?)(?:\?|$)",
            r"list (?:everything |what's |what is )?(?:in|on|at) (?:the |my )?(.+?)(?:\?|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                location = match.group(1).strip()
                if location:
                    return location
        return None

    def _is_item_query(self, text: str) -> Optional[str]:
        patterns = [
            r"where(?:'s| is| are| did i put)(?: the| my)? (.+?)(?:\?|$)",
            r"(?:find|locate)(?: the| my)? (.+?)(?:\?|$)",
            r"(?:i need|looking for)(?: the| my| a)? (.+?)(?:\?|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                item = match.group(1).strip()
                item = re.sub(r'\s+(?:at|is|are|again)$', '', item)
                if item and not self._looks_like_location(item):
                    return item
        return None

    def _is_store(self, text_lower: str) -> Optional[Dict]:
        patterns = [
            r"(?:the |my )?(.+?) (?:is|are|goes?) (?:in|on|under|behind|inside|next to|near|by|at) (?:the |my )?(.+)",
            r"(?:i )?(?:put|placed|stored|keep|left) (?:the |my )?(.+?) (?:in|on|under|behind|inside|next to|near|by|at) (?:the |my )?(.+)",
            r"(?:the |my )?(.+?) (?:in|on|under|behind|at) (?:the |my )?(.+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                item, location = match.group(1).strip(), match.group(2).strip()
                if item and location and not self._looks_like_question(item):
                    return {"item": item, "location": location, "context": None}
        return None

    def _looks_like_question(self, text: str) -> bool:
        question_words = ["where", "what", "which", "how", "when", "why", "who"]
        return any(text.startswith(w) for w in question_words)

    def _looks_like_location(self, text: str) -> bool:
        text_lower = text.lower()
        for word in self.container_words:
            if word in text_lower:
                return True
        if re.search(r'(red|blue|green|black|white|yellow)\s+\w+', text_lower):
            return True
        if re.search(r'(left|right|top|bottom|front|back)\s+\w+', text_lower):
            return True
        return False

    def _is_leave_message(self, text: str) -> Optional[Dict]:
        """Detect 'tell dad I'm going to the store' or 'leave a message for mom'."""
        patterns = [
            r"(?:tell|let) (\w+) (?:that |know )?(.+)",
            r"leave (?:a )?message for (\w+)[,:]?\s*(.+)",
            r"message for (\w+)[,:]?\s*(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                person = match.group(1).strip()
                message = match.group(2).strip()
                # Filter out non-person phrases like "tell me a joke"
                if person.lower() in ("me", "us", "everyone", "a"):
                    continue
                if message:
                    return {"person": person, "message": message}
        return None

    def _is_status_update(self, text: str) -> Optional[Dict]:
        """Detect 'I'm going to the store' or 'dad went to work'."""
        # Speaker updating their own status
        self_patterns = [
            r"i'?m (going to|headed to|heading to|leaving for|off to|at|running to) (.+)",
            r"i (?:will be |am )?(going to|headed to|heading to|leaving for|off to) (.+)",
        ]
        for pattern in self_patterns:
            match = re.search(pattern, text)
            if match:
                action = match.group(1).strip()
                destination = match.group(2).strip()
                return {"person": None, "status": f"{action} {destination}"}

        # Reporting someone else's status — specific verb patterns
        other_patterns = [
            r"(\w+) (?:is |)(going to|headed to|heading to|leaving for|off to|went to|left for) (.+)",
            r"(\w+) is at (.+)",
        ]
        for pattern in other_patterns:
            match = re.search(pattern, text)
            if match:
                groups = match.groups()
                person = groups[0].strip()
                if person.lower() in ("it", "this", "that", "there", "what", "who"):
                    continue
                if len(groups) == 3:
                    action = groups[1].strip()
                    destination = groups[2].strip()
                    status = f"{action} {destination}"
                else:
                    destination = groups[1].strip()
                    status = f"at {destination}"
                return {"person": person, "status": status}

        # Broader match: "[known person] is [doing something] in/at [place]"
        broad_match = re.search(
            r"(\w+) is (.+?) (?:in|at|on) (?:the |my )?(.+)", text)
        if broad_match:
            person = broad_match.group(1).strip()
            p_lower = person.lower()
            # Only match if it's a known person (family name or role word)
            if p_lower in self._family_names or p_lower in self._person_status_words:
                action = broad_match.group(2).strip()
                place = broad_match.group(3).strip()
                return {"person": person, "status": f"{action} in the {place}"}

        return None

    def _is_person_query(self, text: str, family_names: set = None) -> Optional[str]:
        """Detect 'where is dad' when it's about a person, not an item."""
        match = re.search(r"where(?:'s| is| did) (\w+)", text)
        if match:
            person = match.group(1).strip()
            p_lower = person.lower()
            # Check against known role words
            if p_lower in self._person_status_words:
                return person
            # Check against family tree names
            if family_names and p_lower in family_names:
                return person
        return None

    def _parse_introduction(self, text: str) -> Optional[tuple]:
        """
        Try to parse a self-introduction from text.
        Returns (name, relationship) or None.
        """
        text_lower = text.lower().strip()

        # Must match one of the intro trigger phrases
        if not any(text_lower.startswith(p) or f" {p}" in text_lower
                    for p in self._introduce_self_phrases):
            return None

        # Filter out false positives
        false_positives = [
            "this is great", "this is good", "this is nice", "this is fun",
            "this is hard", "this is easy", "this is it", "this is all",
            "this is where", "this is what", "this is how", "this is why",
            "this is the", "this is my", "this is a ", "this is an ",
        ]
        for fp in false_positives:
            if text_lower.startswith(fp):
                return None

        name = None
        relationship = None

        # "this is [Name]" with optional relationship
        match = re.search(
            r"this is ([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)"
            r"(?:,?\s+(?:I'?m|she'?s|he'?s)\s+(.+))?",
            text, re.IGNORECASE
        )
        if match:
            name = match.group(1).strip().title()
            relationship = match.group(2).strip() if match.group(2) else None
            return (name, relationship)

        # "my name is [Name]"
        match = re.search(r"my name is ([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)",
                          text, re.IGNORECASE)
        if match:
            return (match.group(1).strip().title(), None)

        # "I'm [Name]" — filter out non-names
        skip_words = {
            "fine", "good", "great", "okay", "ok", "doing", "here", "ready",
            "back", "home", "tired", "hungry", "happy", "sad", "sorry",
            "not", "just", "going", "looking", "trying", "telling",
        }
        match = re.search(r"I'?m\s+([A-Z][a-z]+)", text)
        if match:
            candidate = match.group(1).strip()
            if candidate.lower() not in skip_words:
                name = candidate.title()
                rel_match = re.search(
                    r"I'?m\s+" + re.escape(candidate) + r",?\s+(.+)",
                    text, re.IGNORECASE
                )
                relationship = rel_match.group(1).strip() if rel_match else None
                return (name, relationship)

        return None
