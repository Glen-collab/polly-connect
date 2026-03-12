"""
ECHO-BRIDGE-INVITE conversational follow-up engine for Polly Connect.

Based on behavioral psychology technique:
  ECHO   - Reflect back a keyword from what the person said
  BRIDGE - Connect emotionally with a warm transitional phrase
  INVITE - Ask a natural follow-up question (template or AI-generated)

Hybrid: templates always work (free), AI follow-ups activate when OPENAI_API_KEY is set.
"""

import logging
import random
import re
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Word lists for keyword extraction ──

# Words to skip when extracting keywords (too generic)
STOP_WORDS = {
    "i", "me", "my", "we", "our", "you", "your", "it", "its", "he", "she",
    "they", "them", "his", "her", "the", "a", "an", "and", "or", "but", "in",
    "on", "at", "to", "for", "of", "with", "was", "were", "is", "are", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "can", "may", "might", "shall", "that",
    "this", "there", "here", "when", "where", "what", "which", "who", "how",
    "not", "no", "yes", "yeah", "yep", "nope", "just", "really", "very",
    "so", "too", "also", "then", "than", "like", "about", "up", "out",
    "if", "from", "into", "over", "after", "before", "between", "under",
    "again", "all", "any", "some", "every", "each", "much", "many", "more",
    "most", "other", "another", "such", "only", "own", "same", "well",
    "know", "think", "remember", "used", "always", "never", "still",
    "something", "thing", "things", "stuff", "lot", "kind", "sort",
    "got", "get", "go", "went", "come", "came", "make", "made", "take",
    "took", "said", "say", "tell", "told", "put", "back", "one", "two",
    # STT filler / garble words
    "um", "uh", "ah", "hmm", "right", "okay", "actually", "basically",
    "literally", "honestly", "obviously", "anyway", "anyways", "whatever",
    "mean", "guess", "sure", "probably", "maybe", "question", "good",
    "great", "nice", "pretty", "gonna", "gotta", "wanna", "kinda",
}

# Words that signal specific emotions
EMOTION_WORDS = {
    "warm": [
        "love", "loved", "loving", "favorite", "special", "beautiful",
        "wonderful", "amazing", "blessed", "grateful", "thankful", "sweet",
        "precious", "dear", "heart", "gentle", "kind", "caring", "warm",
        "cozy", "comfort", "safe", "home", "together", "family", "mama",
        "daddy", "grandma", "grandpa", "baby",
    ],
    "funny": [
        "funny", "laugh", "laughing", "laughed", "hilarious", "crazy",
        "wild", "silly", "goofy", "ridiculous", "joke", "trouble",
        "mischief", "prank", "hysterical", "cracked", "hoot",
    ],
    "nostalgic": [
        "remember", "remembered", "miss", "missed", "missing", "used to",
        "back then", "those days", "old days", "growing up", "childhood",
        "young", "little", "years ago", "long time", "anymore", "gone",
    ],
    "sad": [
        "sad", "hard", "tough", "difficult", "lost", "died", "passed",
        "gone", "miss", "hurt", "pain", "struggle", "cried", "crying",
        "tears", "lonely", "alone", "sick", "worried", "scared",
    ],
}


# ── ECHO templates ──
# {keyword} gets replaced with the extracted keyword/phrase

ECHO_TEMPLATES = [
    "{keyword}...",
    "{keyword}... yeah.",
    "{keyword}...",
    "{keyword}... I can see that.",
    "{keyword}...",
    "{keyword}... wow.",
    "{keyword}...",
    "So {keyword}...",
    "{keyword}... huh.",
    "{keyword}...",
    "{keyword}...",
    "{keyword}... mm-hmm.",
    "Hmm, {keyword}...",
    "{keyword}...",
    "{keyword}... okay.",
    "{keyword}...",
    "Right, {keyword}...",
    "{keyword}...",
    "{keyword}...",
    "{keyword}... that's something.",
]


# ── BRIDGE templates ──
# Organized by detected emotion

BRIDGE_TEMPLATES = {
    "warm": [
        "that sounds like it meant something special.",
        "you can hear the love in that.",
        "that's the kind of thing that stays with you.",
        "sounds like that was a real blessing.",
        "that's a beautiful thing.",
        "that must have been so special.",
        "I can tell that meant a lot to you.",
        "what a sweet memory.",
    ],
    "funny": [
        "that must have been something to see!",
        "oh, I bet that was a sight!",
        "sounds like there was never a dull moment!",
        "that's the kind of thing you never forget!",
        "I would have loved to have seen that!",
        "oh, that's too good!",
        "that had to be hilarious!",
    ],
    "nostalgic": [
        "funny how those things stay with you.",
        "it's amazing what sticks in your memory.",
        "those are the things worth holding onto.",
        "some things you just don't forget.",
        "that's the kind of memory that matters.",
        "funny how those little things stay with you.",
        "those were different times.",
    ],
    "sad": [
        "that must have been really hard.",
        "I'm sorry you went through that.",
        "that's a lot to carry.",
        "some things leave a mark, don't they.",
        "that takes real strength.",
        "I can hear how much that affected you.",
        "thank you for sharing that. That's not easy.",
    ],
    "neutral": [
        "that's interesting.",
        "tell me more about that.",
        "I can picture that.",
        "that's something, isn't it.",
        "huh, that's really something.",
        "I like hearing about that.",
        "that's worth remembering.",
    ],
}


# ── INVITE templates ──
# Template follow-up questions organized by topic

INVITE_TEMPLATES = {
    "person": [
        "What else do you remember about them?",
        "What did they look like?",
        "What would they think about all this if they were here today?",
        "Did they have a saying they always used?",
        "What's the first thing that comes to mind when you think of them?",
        "Who did they remind you of?",
        "Were you two close?",
        "What's the funniest thing they ever did?",
        "Did they have any habits that drove everybody crazy?",
        "What would you give to spend one more day with them?",
        "Did they teach you something nobody else could?",
        "What do you think they'd say to you right now?",
        "Were they the quiet type or the life of the party?",
        "Did other people see them the same way you did?",
        "What made them different from everybody else?",
        "How old were you when you really got to know them?",
        "Did they ever surprise you?",
        "Do you see any of them in yourself?",
        "Do your kids remind you of them at all?",
        "What's a story about them that not many people know?",
    ],
    "food": [
        "What made it so special?",
        "Did anybody ever try to get the recipe?",
        "Could you smell it from outside?",
        "Who else loved it as much as you did?",
        "Did you ever try to make it yourself?",
        "Was it one of those things only they could get right?",
        "What did the kitchen look like when they were making it?",
        "Was there a secret ingredient?",
        "Did everybody fight over the leftovers?",
        "Does the smell of it still take you right back?",
        "Did they make it from scratch every time?",
        "Would they let you help, or did they do it all themselves?",
        "Is there anybody who makes it now?",
        "What would you give to taste it one more time?",
        "Did they ever burn it or mess it up?",
    ],
    "place": [
        "What did it look like?",
        "Can you still picture it in your mind?",
        "Is it still there?",
        "What would you see if you walked through the front door?",
        "What sounds do you remember from there?",
        "Did it feel big or small to you as a kid?",
        "Who else was there with you?",
        "What time of year are you thinking about?",
        "Did it change much over the years?",
        "Have you been back since?",
        "What did it smell like?",
        "Was there a spot that was just yours?",
        "If you closed your eyes, could you walk through it from memory?",
        "What happened to it?",
        "Would your kids even recognize it?",
    ],
    "activity": [
        "How often did you do that?",
        "Who taught you how?",
        "Were you any good at it?",
        "Do you still do it?",
        "What did it feel like?",
        "Did anybody do it with you?",
        "What's the best time you ever had doing it?",
        "Did you ever get in trouble over it?",
        "Is that something kids today would even know about?",
        "Would you do it differently now?",
        "What did people think about it back then?",
        "Did it ever go wrong?",
        "When did you stop? Or do you still?",
        "What made it so much fun?",
        "Was there a trick to it?",
    ],
    "general": [
        "What happened after that?",
        "How old were you then?",
        "Who else was there?",
        "What year was that, do you remember?",
        "What did people say about it?",
        "Did it change anything for you?",
        "Looking back, how do you feel about it now?",
        "Would you do it the same way again?",
        "Did anybody else know about that?",
        "Is that a story you've told before, or is this the first time?",
        "What made you think of that?",
        "How did that make you feel at the time?",
        "Was that a turning point for you?",
        "Does anything like that still happen today?",
        "What do you think your grandkids would say about that?",
        "Is that something that shaped who you are?",
        "Would your family be surprised to hear that story?",
        "What's the part of that story you never told anybody?",
        "If you could go back to that moment, what would you say?",
        "Is there more to that story?",
    ],
}

# Topic detection keywords
TOPIC_KEYWORDS = {
    "person": [
        "he", "she", "him", "her", "they", "mom", "mama", "mother", "dad",
        "daddy", "father", "grandma", "grandpa", "grandmother", "grandfather",
        "aunt", "uncle", "brother", "sister", "cousin", "friend", "neighbor",
        "teacher", "preacher", "pastor", "boss", "wife", "husband",
    ],
    "food": [
        "cook", "cooked", "cooking", "bake", "baked", "baking", "recipe",
        "kitchen", "supper", "dinner", "lunch", "breakfast", "meal", "pie",
        "cake", "bread", "chicken", "beans", "cornbread", "biscuits",
        "gravy", "stew", "soup", "fry", "fried", "eat", "ate", "eating",
        "taste", "tasted", "smell", "smelled", "delicious", "food",
    ],
    "place": [
        "house", "home", "church", "school", "store", "farm", "field",
        "creek", "river", "lake", "road", "street", "town", "city",
        "porch", "yard", "garden", "barn", "room", "bedroom", "kitchen",
        "neighborhood", "corner", "downtown", "building",
    ],
    "activity": [
        "play", "played", "playing", "work", "worked", "working", "fish",
        "fishing", "hunt", "hunting", "sing", "singing", "sang", "dance",
        "danced", "dancing", "drive", "drove", "driving", "build", "built",
        "building", "run", "running", "ran", "swim", "swimming", "ride",
        "riding", "rode", "game", "sport",
    ],
}


class EchoEngine:
    """
    ECHO-BRIDGE-INVITE conversational follow-up generator.

    Hybrid approach:
    - Template-based follow-ups always work (no cost, no API key needed)
    - AI follow-ups via FollowupGenerator when OPENAI_API_KEY is set
    - Narrative arc awareness guides follow-ups through critical thinking steps
    """

    def __init__(self, followup_generator=None, narrative_arc=None):
        self.followup_gen = followup_generator
        self.narrative_arc = narrative_arc
        self._ai_available = followup_generator is not None and followup_generator.available

    async def generate_followup(self, question: str, answer: str,
                                followup_count: int = 0,
                                bucket: str = None,
                                critical_thinking_step: int = 1) -> str:
        """
        Generate a full ECHO + BRIDGE + INVITE response.

        Args:
            question: The question that was asked
            answer: The user's answer text
            followup_count: How many follow-ups already given (for variety)
            bucket: Current Jungian bucket (for arc-guided follow-ups)
            critical_thinking_step: Current step 1-6 (for deepening)

        Returns:
            Complete response string
        """
        if not answer or not answer.strip():
            return "Take your time. I'm listening."

        keyword = self._extract_keyword(answer)
        emotion = self._detect_emotion(answer)
        topic = self._detect_topic(answer)

        # ECHO
        echo = self._make_echo(keyword)

        # BRIDGE
        bridge = self._make_bridge(emotion)

        # INVITE — now arc-aware
        invite = await self._make_invite(
            question, answer, topic, followup_count,
            bucket=bucket, critical_thinking_step=critical_thinking_step,
        )

        return f"{echo} {bridge} {invite}"

    def generate_closing(self, speaker_name: str = None) -> str:
        """Generate a warm closing after max follow-ups reached."""
        closings = [
            "That was a wonderful story. Thank you for sharing{name_part}.",
            "I really enjoyed hearing that{name_part}. Thank you.",
            "That's the kind of story worth holding onto{name_part}.",
            "Thank you for sharing that with me{name_part}. That was special.",
            "What a story{name_part}. I'm glad you told me that.",
            "That was really something{name_part}. Thank you for trusting me with that.",
        ]
        name_part = f", {speaker_name}" if speaker_name else ""
        closing = random.choice(closings)
        return closing.format(name_part=name_part)

    # ── ECHO ──

    def _extract_keyword(self, text: str) -> str:
        """Extract a meaningful keyword or short phrase from the answer."""
        words = text.split()

        # Try to find a 2-3 word phrase that's meaningful
        clean_words = [w.strip(".,!?;:'\"") for w in words]
        meaningful = [w for w in clean_words if w.lower() not in STOP_WORDS and len(w) > 2]

        if not meaningful:
            # Fallback: use last few words
            if len(words) >= 3:
                return " ".join(words[-3:]).strip(".,!?")
            return text.strip(".,!?")[:40]

        # Try to find adjacent meaningful words for a phrase
        for i in range(len(clean_words) - 1):
            w1 = clean_words[i]
            w2 = clean_words[i + 1]
            if w1.lower() not in STOP_WORDS and w2.lower() not in STOP_WORDS:
                if len(w1) > 2 and len(w2) > 2:
                    return f"{w1} {w2}".lower()

        # Single best keyword
        return meaningful[0].lower()

    def _make_echo(self, keyword: str) -> str:
        """Generate the ECHO part — reflecting back a keyword."""
        template = random.choice(ECHO_TEMPLATES)
        # Capitalize first letter of keyword for sentence start
        kw = keyword.capitalize() if template.startswith("{keyword}") else keyword
        return template.format(keyword=kw)

    # ── BRIDGE ──

    def _detect_emotion(self, text: str) -> str:
        """Detect the dominant emotion in the text."""
        text_lower = text.lower()
        scores = {}
        for emotion, words in EMOTION_WORDS.items():
            score = sum(1 for w in words if w in text_lower)
            scores[emotion] = score

        if max(scores.values()) == 0:
            return "neutral"

        return max(scores, key=scores.get)

    def _make_bridge(self, emotion: str) -> str:
        """Generate the BRIDGE part — emotional connection."""
        templates = BRIDGE_TEMPLATES.get(emotion, BRIDGE_TEMPLATES["neutral"])
        return random.choice(templates)

    # ── INVITE ──

    def _detect_topic(self, text: str) -> str:
        """Detect the topic category of the answer."""
        text_lower = text.lower()
        scores = {}
        for topic, keywords in TOPIC_KEYWORDS.items():
            score = sum(1 for k in keywords if k in text_lower.split())
            scores[topic] = score

        if max(scores.values()) == 0:
            return "general"

        return max(scores, key=scores.get)

    async def _make_invite(self, question: str, answer: str,
                           topic: str, followup_count: int,
                           bucket: str = None,
                           critical_thinking_step: int = 1) -> str:
        """Generate the INVITE part — the follow-up question.

        Uses narrative arc deepening when available:
        Step 1→2: move from scene-setting to specific memory
        Step 2→3: move to emotional response
        Step 3→4: move to turning point
        Step 4→5: move to social context
        Step 5→6: move to reflection/wisdom
        """
        # Try narrative arc deepening first (critical thinking progression)
        if self.narrative_arc and critical_thinking_step < 6:
            deepening = self.narrative_arc.get_deepening_prompt(critical_thinking_step)
            if deepening:
                # On odd follow-ups use the deepening prompt for arc progression
                if followup_count % 2 == 1:
                    return deepening

        # Always try AI if available — GPT generates contextual follow-ups
        if self._ai_available:
            try:
                ai_questions = await self.followup_gen.generate(question, answer, count=1)
                if ai_questions:
                    return ai_questions[0]
            except Exception as e:
                logger.warning(f"AI follow-up failed, falling back to templates: {e}")

        # Template fallback — prefer topic-specific
        templates = INVITE_TEMPLATES.get(topic, INVITE_TEMPLATES["general"])
        return random.choice(templates)
