"""
Memory metadata extractor for Polly Connect.

Extracts structured metadata from raw story transcripts:
  - People mentioned (family words + capitalized names)
  - Locations (place keywords)
  - Emotions (12-category word lists)
  - Life phase (keyword detection)
  - Jungian bucket (from question context + content analysis)
  - Text summary (first sentence)

No ML/spacy required — pure keyword heuristics.
"""

import logging
import re
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ── People detection ──

RELATIONSHIP_WORDS = {
    "mom", "mama", "mother", "dad", "daddy", "father", "papa",
    "grandma", "grandmother", "granny", "nana", "meemaw",
    "grandpa", "grandfather", "papaw", "pawpaw",
    "brother", "sister", "son", "daughter",
    "aunt", "auntie", "uncle",
    "cousin", "nephew", "niece",
    "husband", "wife", "spouse",
    "friend", "neighbor", "teacher", "preacher", "pastor", "boss",
    "baby", "child", "kids", "children",
}

# ── Location detection ──

PLACE_WORDS = {
    "house", "home", "farm", "church", "school", "store", "shop",
    "hospital", "barn", "creek", "river", "lake", "pond", "mountain",
    "beach", "ocean", "woods", "forest", "field", "garden", "yard",
    "porch", "kitchen", "bedroom", "bathroom", "living room",
    "basement", "attic", "garage", "driveway", "sidewalk",
    "road", "street", "highway", "bridge", "park", "playground",
    "downtown", "uptown", "neighborhood", "town", "city", "country",
    "restaurant", "diner", "cafe", "bar", "tavern",
    "factory", "mill", "mine", "office", "warehouse",
}

# ── Emotion detection (12 categories) ──

EMOTION_KEYWORDS = {
    "joy": ["happy", "joy", "joyful", "excited", "thrilled", "delighted",
            "wonderful", "amazing", "blessed"],
    "love": ["love", "loved", "loving", "adore", "cherish", "precious",
             "dear", "sweet", "tender"],
    "nostalgia": ["remember", "miss", "missed", "those days", "back then",
                  "used to", "anymore", "gone"],
    "sadness": ["sad", "cried", "crying", "tears", "heartbreak", "loss",
                "grief", "mourning"],
    "fear": ["scared", "afraid", "terrified", "worried", "anxious",
             "nervous", "panic"],
    "anger": ["angry", "mad", "furious", "upset", "frustrated", "annoyed"],
    "pride": ["proud", "accomplished", "achievement", "earned", "built",
              "created"],
    "gratitude": ["grateful", "thankful", "blessed", "fortunate", "lucky",
                  "appreciate"],
    "humor": ["funny", "hilarious", "laugh", "laughed", "joke", "silly",
              "crazy", "wild"],
    "courage": ["brave", "courage", "stood up", "fought", "persevered",
                "endured", "survived"],
    "peace": ["peaceful", "calm", "quiet", "serene", "content",
              "comfortable", "cozy", "safe"],
    "adventure": ["adventure", "explore", "discovered", "traveled",
                  "journey", "wandered"],
}

# ── Life phase detection ──

LIFE_PHASE_KEYWORDS = {
    "childhood": [
        "kid", "child", "little", "young", "school", "grade", "playground",
        "growing up", "when i was little", "when i was young", "as a kid",
        "elementary", "recess", "toys", "cartoon",
    ],
    "adolescence": [
        "teenager", "teen", "high school", "junior high", "middle school",
        "prom", "football", "basketball", "dating", "driver", "license",
        "first car", "summer job",
    ],
    "young_adult": [
        "college", "university", "first job", "apartment", "engaged",
        "married", "wedding", "newlywed", "moved out", "on my own",
        "military", "service", "enlisted", "drafted",
    ],
    "adult": [
        "career", "promotion", "mortgage", "pregnant", "baby",
        "raising", "parent", "company", "bought", "built",
    ],
    "midlife": [
        "retirement", "retired", "grandchild", "grandkid", "empty nest",
        "looking back", "in my fifties", "in my sixties",
    ],
    "elder": [
        "nowadays", "these days", "at my age", "getting older",
        "my generation", "back in my day", "young people today",
    ],
}

# ── Bucket inference from content ──

BUCKET_CONTENT_KEYWORDS = {
    "return_with_knowledge": [
        "learned", "lesson", "advice", "wisdom", "legacy", "pass on",
        "tell someone", "grandkids should know",
    ],
    "transformation": [
        "changed", "different", "realized", "grew", "transformed",
        "never the same", "woke up", "saw things differently",
    ],
    "trials_allies_enemies": [
        "hard", "struggle", "helped", "enemy", "betrayed", "stood by",
        "let me down", "pulled through", "tough time",
    ],
    "crossing_threshold": [
        "decided", "chose", "left", "started", "moved", "no going back",
        "took the leap", "walked away", "new chapter",
    ],
    "call_to_adventure": [
        "happened", "unexpected", "surprise", "suddenly", "out of nowhere",
        "everything changed", "moment", "turning point",
    ],
}

# Skip these when looking for proper names
NAME_SKIP = {
    "I", "God", "Jesus", "Christ", "Christmas", "Thanksgiving", "Easter",
    "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
    "The", "And", "But", "We", "They", "He", "She", "It", "You",
    "So", "Well", "Yeah", "Yes", "No", "Oh", "Now", "Then",
}


class MemoryExtractor:
    """Extracts structured metadata from raw story transcripts."""

    def extract(self, text: str, question: str = None,
                speaker: str = None, bucket_hint: str = None) -> Dict:
        """
        Extract structured memory metadata from raw transcript text.

        Args:
            text: The raw transcript
            question: The question that prompted this answer (for bucket inference)
            speaker: Who said it
            bucket_hint: Pre-assigned bucket from question data

        Returns dict with: people, locations, emotions, life_phase, bucket, text_summary, text
        """
        if not text:
            return self._empty_memory(speaker)

        people = self._extract_people(text)
        locations = self._extract_locations(text)
        emotions = self._extract_emotions(text)
        life_phase = self._detect_life_phase(text)

        # Bucket assignment: hint > question inference > content inference
        bucket = bucket_hint
        if not bucket and question:
            bucket = self._infer_bucket_from_question(question)
        if not bucket:
            bucket = self._infer_bucket_from_content(text, emotions)

        summary = self._summarize(text)

        return {
            "speaker": speaker,
            "people": sorted(people),
            "locations": sorted(locations),
            "emotions": sorted(emotions),
            "life_phase": life_phase or "unknown",
            "bucket": bucket or "ordinary_world",
            "text_summary": summary,
            "text": text,
        }

    def compute_fingerprint(self, memory: Dict) -> str:
        """
        Create a fingerprint for duplicate/overlap detection.
        Combines people + locations + emotions + bucket into a hashable string.
        """
        parts = [
            memory.get("bucket", ""),
            "|".join(memory.get("people", [])),
            "|".join(memory.get("locations", [])),
            "|".join(memory.get("emotions", [])),
            memory.get("life_phase", ""),
        ]
        return "::".join(parts).lower()

    def is_similar(self, mem_a: Dict, mem_b: Dict, threshold: float = 0.5) -> bool:
        """Check if two memories overlap significantly (for chapter dedup)."""
        # Compare people overlap
        people_a = set(p.lower() for p in mem_a.get("people", []))
        people_b = set(p.lower() for p in mem_b.get("people", []))
        if people_a and people_b:
            people_overlap = len(people_a & people_b) / max(len(people_a | people_b), 1)
        else:
            people_overlap = 0

        # Compare emotion overlap
        emo_a = set(mem_a.get("emotions", []))
        emo_b = set(mem_b.get("emotions", []))
        if emo_a and emo_b:
            emo_overlap = len(emo_a & emo_b) / max(len(emo_a | emo_b), 1)
        else:
            emo_overlap = 0

        # Same bucket = boost
        bucket_match = 1.0 if mem_a.get("bucket") == mem_b.get("bucket") else 0.0

        score = (people_overlap * 0.4) + (emo_overlap * 0.3) + (bucket_match * 0.3)
        return score >= threshold

    # ── Internal extraction methods ──

    def _empty_memory(self, speaker: str = None) -> Dict:
        return {
            "speaker": speaker,
            "people": [],
            "locations": [],
            "emotions": [],
            "life_phase": "unknown",
            "bucket": "ordinary_world",
            "text_summary": "",
            "text": "",
        }

    def _extract_people(self, text: str) -> Set[str]:
        """Extract mentioned people from text."""
        people = set()
        text_lower = text.lower()

        for word in RELATIONSHIP_WORDS:
            if word in text_lower:
                # Look for "mama Jo" — relationship word followed by a proper name
                # The name must start with uppercase and not be a common verb/adj
                common_non_names = {
                    "used", "made", "said", "told", "gave", "did", "was", "had",
                    "always", "never", "would", "could", "just", "really",
                }
                pattern = rf'\b(?:my |our |his |her )?{re.escape(word)}\s+([A-Z][a-z]+)\b'
                matches = re.finditer(pattern, text)
                found_named = False
                for m in matches:
                    candidate = m.group(1)
                    if candidate.lower() not in common_non_names:
                        people.add(f"{word.title()} {candidate}")
                        found_named = True
                if not found_named:
                    if re.search(rf'\b{re.escape(word)}\b', text_lower):
                        people.add(word.title())

        # Standalone capitalized names (heuristic)
        words = text.split()
        for i, word in enumerate(words):
            clean = word.strip(".,!?;:'\"()")
            if (clean and clean[0].isupper() and clean not in NAME_SKIP
                    and len(clean) > 1 and i > 0 and not words[i - 1].endswith('.')):
                people.add(clean)

        return people

    def _extract_locations(self, text: str) -> Set[str]:
        """Extract mentioned locations from text."""
        locations = set()
        text_lower = text.lower()

        for place in PLACE_WORDS:
            if place in text_lower:
                pattern = (
                    rf"(?:the |our |my |his |her |grandma'?s? |mama'?s? )?"
                    rf"(?:\w+ )?{re.escape(place)}"
                )
                match = re.search(pattern, text_lower)
                if match:
                    locations.add(match.group().strip())
                else:
                    locations.add(place)

        return locations

    def _extract_emotions(self, text: str) -> Set[str]:
        """Detect emotion categories present in the text."""
        emotions = set()
        text_lower = text.lower()

        for emotion, keywords in EMOTION_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    emotions.add(emotion)
                    break

        return emotions

    def _detect_life_phase(self, text: str) -> Optional[str]:
        """Detect the life phase being discussed."""
        text_lower = text.lower()
        scores = {}

        for phase, keywords in LIFE_PHASE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[phase] = score

        if not scores:
            return None
        return max(scores, key=scores.get)

    def _infer_bucket_from_question(self, question: str) -> Optional[str]:
        """Infer Jungian bucket from the question that was asked."""
        q_lower = question.lower()

        if any(w in q_lower for w in ["normal day", "grew up", "neighborhood",
                                       "house", "cook", "supper", "look like"]):
            return "ordinary_world"
        if any(w in q_lower for w in ["happened", "changed", "moment",
                                       "stands out", "remember when"]):
            return "call_to_adventure"
        if any(w in q_lower for w in ["decision", "choice", "turned",
                                       "leaving", "moved", "married"]):
            return "crossing_threshold"
        if any(w in q_lower for w in ["helped", "taught", "hard part",
                                       "struggle", "tough", "hardest"]):
            return "trials_allies_enemies"
        if any(w in q_lower for w in ["different", "learned", "changed you",
                                       "realized", "grew"]):
            return "transformation"
        if any(w in q_lower for w in ["advice", "tell someone", "grandkids",
                                       "legacy", "pass on", "wisdom",
                                       "remember about you"]):
            return "return_with_knowledge"

        return None

    def _infer_bucket_from_content(self, text: str, emotions: Set[str]) -> str:
        """Infer bucket from content when question context isn't available."""
        text_lower = text.lower()

        for bucket, keywords in BUCKET_CONTENT_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    return bucket

        if {"fear", "courage", "adventure"} & emotions:
            return "call_to_adventure"

        return "ordinary_world"

    def infer_life_phase_from_date(self, date_str: str, birth_year: int = None) -> Optional[str]:
        """Infer life phase from a photo date string and optional birth year.
        Supports formats like '1964', 'Summer 1964', '1964-06-15', 'June 1964'."""
        if not date_str:
            return None
        # Extract 4-digit year
        match = re.search(r'(19\d{2}|20\d{2})', date_str)
        if not match:
            return None
        year = int(match.group(1))
        if not birth_year:
            return None
        age = year - birth_year
        if age < 0:
            return None
        if age <= 12:
            return "childhood"
        if age <= 18:
            return "adolescence"
        if age <= 30:
            return "young_adult"
        if age <= 50:
            return "adult"
        if age <= 70:
            return "midlife"
        return "elder"

    def _summarize(self, text: str) -> str:
        """Create a brief summary (first sentence, max 120 chars)."""
        sentences = re.split(r'[.!?]+', text)
        if sentences and len(sentences[0].strip()) > 10:
            summary = sentences[0].strip()
            if len(summary) > 120:
                return summary[:117] + "..."
            return summary
        if len(text) > 120:
            return text[:117] + "..."
        return text
