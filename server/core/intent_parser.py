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
            "let me share", "i have a story",
            "i want to share", "record my story", "take my story",
            "story time", "i want to record", "i have something to share",
            "i want to tell a story", "let me tell you something",
            "can i tell you something", "i got a story",
            "i have a memory to share", "can i share a story",
        ]
        self._hear_stories_phrases = [
            "tell me about", "play back",
            "what stories", "any stories about", "any stories",
            "read me a story", "play a story", "do you have any stories",
            "what have you heard about", "play my stories", "read my stories",
            "what did grandma say", "what did she say", "what did he say",
            "what has grandma said", "what has she said",
            "read me my stories", "tell me one of my stories",
            "read a story", "tell me my story", "share a story",
            "read back my stories", "read me one of my stories",
            "narrate a story", "story reading",
            "tell me a story", "say a story", "give me a story",
            "got any stories", "hear a story", "let's hear a story",
            "i want to hear a story", "i'd like to hear a story",
            "let me hear a story", "can you tell me a story",
            "do you have a story",
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
            "never mind", "nevermind", "forget it",
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
            "i'm heading out", "heading out", "i'm leaving",
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
            "verse about", "scripture", "read me a psalm", "read me a salm",
            "psalm", "salm", "read me a proverb", "proverb",
            "read me from the bible", "daily verse",
            "read me some scripture", "what does the bible say",
            "i need a bible verse", "give me some scripture",
            "read from the bible", "do you have a verse",
            "can you read me a verse", "what's today's verse",
            "inspirational verse", "devotional",
            "verse of the day", "daily bible verse",
        ]
        self._prayer_phrases = [
            # Direct prayer requests
            "say a prayer", "pray for me", "pray with me",
            "let's pray", "let us pray", "can you pray",
            "i need a prayer", "prayer", "pray",
            "say a prayer for me", "will you pray",
            "i want to pray", "help me pray",
            "lead me in prayer", "lead a prayer",
            "can we pray", "would you pray",
            "pray for us", "pray over me",
            # Time-based
            "bedtime prayer", "goodnight prayer",
            "nighttime prayer", "evening prayer",
            "morning prayer", "start the day with prayer",
            # Emotional triggers (natural speech)
            "i'm having a hard day", "i need some hope",
            "i'm feeling down", "i'm feeling low",
            "i'm worried", "i'm scared", "i'm anxious",
            "i feel alone", "i feel lonely",
            "i miss him", "i miss her", "i miss them",
            "i'm struggling", "things are tough",
            "give me strength", "i need strength",
            "i need peace", "i need comfort",
            "i'm thankful", "i'm grateful", "i'm blessed",
            "thank the lord", "praise god", "praise the lord",
            "bless this day", "bless my family",
            # Family-specific
            "pray for my family", "family prayer",
            "pray for my kids", "pray for the children",
            "pray for my grandchildren", "pray for my grandkids",
        ]
        self._nostalgia_phrases = [
            "tell me something from the old days", "take me back",
            "the good old days", "nostalgia",
            "what was it like back then",
            "reminisce", "let's reminisce", "remember the old days",
            "tell me something from my childhood",
            "back in my day",
            "what was it like growing up",
            "memory lane", "take me down memory lane",
            "tell me something nostalgic",
            "the old days", "back in the day",
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
            "weather today", "the weather", "farmer's almanac", "forecast",
            "how's the weather", "what's it like outside",
            "is it going to rain", "what's the forecast",
            "what's the weather like", "weather report",
            "do i need an umbrella", "is it cold outside",
            "what's it going to be like this week",
            "what's the temperature", "temperature outside",
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

        # Normalize contractions: "whats" → "what's", "im" → "i'm", "dont" → "don't"
        # so phrases match regardless of whether STT includes apostrophes
        contraction_map = {
            "whats ": "what's ", "thats ": "that's ", "hows ": "how's ",
            "todays ": "today's ", "lets ": "let's ", "dont ": "don't ",
            "didnt ": "didn't ", "doesnt ": "doesn't ", "cant ": "can't ",
            "wont ": "won't ", "isnt ": "isn't ", "youre ": "you're ",
        }
        for abbrev, full in contraction_map.items():
            text_lower = text_lower.replace(abbrev, full)
        # Word-boundary contractions that can match inside other words
        text_lower = re.sub(r'\bim ', "i'm ", text_lower)
        text_lower = re.sub(r'\bive ', "i've ", text_lower)

        # ── Family storytelling intents (check first, order matters) ──

        if self._matches(text_lower, self._story_progress_phrases):
            return {"intent": "story_progress", "confidence": 0.95}

        if self._matches(text_lower, self._family_question_phrases):
            return {"intent": "family_question", "confidence": 0.95}

        if self._matches(text_lower, self._hear_stories_phrases):
            # Extract who they want to hear about
            query = None
            # Longer "about" phrases first so they capture the full topic
            for phrase in [
                "tell me a story about", "say a story about",
                "give me a story about", "read me a story about",
                "share a story about", "hear a story about",
                "play a story about", "narrate a story about",
                "can you tell me a story about", "i want to hear a story about",
                "i'd like to hear a story about", "do you have a story about",
                "do you have any stories about", "got any stories about",
                "any stories about", "story about",
                "tell me about", "what have you heard about",
                "what did", "what has",
            ]:
                if phrase in text_lower:
                    idx = text_lower.index(phrase) + len(phrase)
                    query = text_lower[idx:].strip().rstrip("?. ")
                    if not query:
                        query = None
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
            elif "psalm" in text_lower or "salm" in text_lower:
                topic = "Psalm"
            elif "proverb" in text_lower:
                topic = "Proverb"
            return {"intent": "bible_verse", "topic": topic, "confidence": 0.9}

        # Check for blessing playback (recorded voice prayers) before AI prayers
        blessing_result = self._is_play_blessing(text_lower)
        if blessing_result:
            return blessing_result

        if self._matches(text_lower, self._prayer_phrases):
            theme = None
            pray_for = None  # specific person to pray for

            # Time-based
            if any(w in text_lower for w in ["bedtime", "goodnight", "nighttime", "evening", "sleep"]):
                theme = "rest"
            elif any(w in text_lower for w in ["morning", "start the day", "new day"]):
                theme = "strength"
            # Emotional categories
            elif any(w in text_lower for w in ["worried", "worry", "anxious", "anxiety", "scared", "fear", "nervous"]):
                theme = "anxiety"
            elif any(w in text_lower for w in ["miss him", "miss her", "miss them", "passed away", "lost", "grief", "heaven"]):
                theme = "grief"
            elif any(w in text_lower for w in ["alone", "lonely", "loneliness", "isolated", "by myself"]):
                theme = "loneliness"
            elif any(w in text_lower for w in ["hard day", "tough", "struggling", "difficult", "having a hard"]):
                theme = "strength"
            elif any(w in text_lower for w in ["heal", "healing", "sick", "health", "surgery", "doctor", "pain"]):
                theme = "healing"
            elif any(w in text_lower for w in ["forgive", "forgiveness", "let go", "bitter", "angry"]):
                theme = "forgiveness"
            elif any(w in text_lower for w in ["peace", "calm", "quiet", "still", "rest", "comfort", "grace", "mercy"]):
                theme = "peace"
            elif any(w in text_lower for w in ["hope", "hopeful", "hopeless", "feeling down", "feeling low", "down"]):
                theme = "hope"
            elif any(w in text_lower for w in ["strength", "strong", "courage", "brave", "resilience", "resilient", "perseverance", "endurance"]):
                theme = "strength"
            elif any(w in text_lower for w in ["faith", "believe", "trust", "doubt", "wisdom", "guidance", "guide"]):
                theme = "faith"
            elif any(w in text_lower for w in ["thank", "grateful", "blessing", "thankful", "blessed", "bless", "praise", "glory", "glorious"]):
                theme = "gratitude"
            elif any(w in text_lower for w in ["purpose", "meaning", "legacy", "why am i"]):
                theme = "purpose"
            elif any(w in text_lower for w in ["happy", "happiness", "joy", "celebrate", "celebration", "wonderful"]):
                theme = "joy"
            # Family
            elif any(w in text_lower for w in ["kid", "kids", "children", "grandkid", "grandchildren", "grandson", "granddaughter", "family"]):
                theme = "family"

            # Check for "pray for [person/topic]" pattern
            pray_for_match = re.search(r'pray(?:er)?\s+(?:for|over)\s+(?:my\s+)?(.+?)(?:\s+please)?$', text_lower)
            if pray_for_match:
                target = pray_for_match.group(1).strip()
                # Skip only truly generic self-references
                skip = {"me", "us", "the family", "my family", "the kids"}
                if target and target not in skip:
                    # Check if target matches a known family member
                    is_family = False
                    if self._family_names:
                        for fn in self._family_names:
                            if fn.lower() == target or fn.lower() in target:
                                is_family = True
                                pray_for = fn  # use proper casing from family tree
                                theme = None  # person prayer, not themed
                                break
                    if not is_family:
                        # Not a family member — still pass it through
                        # "world peace", "the troops", "grace", "healing" all work
                        pray_for = target

            return {"intent": "prayer", "theme": theme, "pray_for": pray_for, "confidence": 0.9}

        if self._matches(text_lower, self._nostalgia_phrases):
            return {"intent": "nostalgia", "confidence": 0.9}

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

        # "I found it" / "got it" / "never mind"
        if self._is_found_it(text_lower):
            return {"intent": "found_it", "confidence": 0.9}

        delete_match = self._is_delete(text_lower)
        if delete_match:
            return {"intent": "delete", "item": delete_match, "confidence": 0.9}

        # "I can't find the hammer" / "I lost my keys"
        cant_find = self._is_cant_find(text_lower)
        if cant_find:
            return {"intent": "retrieve_item", "item": cant_find, "mom_mode": True, "confidence": 0.9}

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
                "prep": store_result.get("prep", "in"),
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

    def _is_play_blessing(self, text: str) -> Optional[Dict]:
        """Detect 'play a blessing' / 'play dad's meal blessing' etc."""
        import re

        # Category mapping — what the user might say → DB category
        category_map = {
            "meal": "grace", "mealtime": "grace", "supper": "grace",
            "dinner": "grace", "lunch": "grace", "breakfast": "grace",
            "food": "grace", "grace": "grace", "table": "grace",
            "bedtime": "bedtime", "goodnight": "bedtime", "nighttime": "bedtime",
            "evening": "bedtime", "sleep": "bedtime", "night": "bedtime",
            "morning": "morning", "wake up": "morning", "sunrise": "morning",
            "general": "general", "gratitude": "gratitude", "thanks": "gratitude",
            "thankful": "gratitude",
        }

        # Patterns for playing a blessing
        patterns = [
            r"(?:play|give)(?: me)? (?:a |the |my )?(?:(\w+)(?:'s|s))?\s*(?:(\w+)\s+)?blessing",
            r"(?:play|give)(?: me)? (?:a |the |my )?(?:(\w+)(?:'s|s))?\s*(?:(\w+)\s+)?prayer recording",
            r"(?:play|give)(?: me)? (?:a |the )?(?:(\w+)(?:'s|s))?\s*(?:recorded |voice )?(?:(\w+)\s+)?prayer",
            r"(?:can you |could you |i want )(?:play|hear|say)(?: me)? (?:a |the )?(?:(\w+)(?:'s|s))?\s*(?:(\w+)\s+)?blessing",
            r"let(?:'s| me) hear (?:(\w+)(?:'s|s))?\s*(?:(\w+)\s+)?blessing",
            r"(?:play|give)(?: me)? (?:a |the )?(\w+) blessing",
            r"(?:say|read)(?: me)? (?:a |the |my )?(?:(\w+)\s+)?blessing",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                groups = match.groups()
                speaker = None
                category = None

                for g in groups:
                    if g:
                        g_lower = g.lower()
                        if g_lower in category_map:
                            category = category_map[g_lower]
                        elif g_lower not in ("a", "the", "my", "play", "can", "you"):
                            # Probably a person name
                            speaker = g

                return {
                    "intent": "play_blessing",
                    "speaker": speaker,
                    "category": category,
                    "confidence": 0.9,
                }

        # Simple triggers without regex
        simple_triggers = [
            "play a blessing", "play blessing", "play a recorded blessing",
            "play a voice blessing", "play my blessing",
            "play a recorded prayer", "play a voice prayer",
            "play me a blessing", "give me a blessing",
            "say a blessing", "read a blessing",
            "meal blessing", "mealtime blessing", "dinner blessing",
            "supper blessing", "bedtime blessing", "morning blessing",
            "play me a meal blessing", "give me a meal blessing",
            "play me a dinner blessing", "play me a bedtime blessing",
            "say a meal blessing", "say grace",
        ]
        if any(t in text for t in simple_triggers):
            # Try to extract category from the trigger text
            cat = None
            for word, mapped in category_map.items():
                if word in text:
                    cat = mapped
                    break
            return {"intent": "play_blessing", "speaker": None, "category": cat, "confidence": 0.9}

        return None

    def _is_found_it(self, text: str) -> bool:
        patterns = [
            r"^i found it", r"^found it", r"^never ?mind", r"^got it",
            r"^i see it", r"^i found the", r"^i found my",
        ]
        for p in patterns:
            if re.search(p, text):
                return True
        return False

    def _is_cant_find(self, text: str) -> Optional[str]:
        patterns = [
            r"i can'?t find (?:the |my |a )?(.+?)(?:\?|$)",
            r"i lost (?:the |my |a )?(.+?)(?:\?|$)",
            r"i'?m looking for (?:the |my |a )?(.+?)(?:\?|$)",
            r"have you seen (?:the |my |a )?(.+?)(?:\?|$)",
            r"i can'?t remember where (?:the |my |a )?(.+?)(?:\s+is|\?|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                item = match.group(1).strip()
                item = re.sub(r'\s+(?:at|is|are|again)$', '', item)
                if item:
                    return item
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
            r"(?:the |my )?(.+?) (?:is|are|goes?) (in|on|under|behind|inside|next to|near|by|at) (?:the |my )?(.+)",
            r"(?:i )?(?:put|placed|stored|keep|left) (?:the |my )?(.+?) (in|on|under|behind|inside|next to|near|by|at) (?:the |my )?(.+)",
            r"(?:the |my )?(.+?) (in|on|under|behind|at) (?:the |my )?(.+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                item = match.group(1).strip()
                prep = match.group(2).strip()
                location = match.group(3).strip()
                if item and location and not self._looks_like_question(item):
                    return {"item": item, "location": location, "prep": prep, "context": None}
        return None

    def _looks_like_question(self, text: str) -> bool:
        question_words = ["where", "what", "which", "how", "when", "why", "who"]
        return any(text.startswith(w) for w in question_words)

    def _looks_like_location(self, text: str) -> bool:
        text_lower = text.lower()
        for word in self.container_words:
            if re.search(r'\b' + re.escape(word) + r'\b', text_lower):
                return True
        if re.search(r'(red|blue|green|black|white|yellow)\s+\w+', text_lower):
            return True
        if re.search(r'(left|right|top|bottom|front|back)\s+\w+', text_lower):
            return True
        return False

    def _is_leave_message(self, text: str) -> Optional[Dict]:
        """Detect 'tell dad I'm going to the store' or 'leave a message for mom'."""
        patterns = [
            r"\b(?:tell|let) (\w+) (?:that |know )?(.+)",
            r"\bleave (?:a )?message for (\w+)[,:]?\s*(.+)",
            r"\bmessage for (\w+)[,:]?\s*(.+)",
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
            r"i'?m (going to|going for|headed to|heading to|leaving for|off to|at|running to|out for) (.+)",
            r"i (?:will be |am )?(going to|going for|headed to|heading to|leaving for|off to|out for) (.+)",
        ]
        for pattern in self_patterns:
            match = re.search(pattern, text)
            if match:
                action = match.group(1).strip()
                destination = match.group(2).strip()
                # "going to bed/sleep" is a goodbye, not a status update
                if destination in ("bed", "sleep"):
                    return None
                return {"person": None, "status": f"{action} {destination}"}

        # Reporting someone else's status — specific verb patterns
        other_patterns = [
            r"(\w+) (?:is |)(going to|going for|headed to|heading to|leaving for|off to|went to|went for|left for|out for) (.+)",
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
