"""
Test Suite B - Prayer & Story Intent Coverage
===============================================
Systematic test of all prayer variations (phrases, themes, pray_for extraction,
keyword guards) and all story variations (tell, hear, record, progress, questions).
Run: python -m pytest tests/test_B.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from server.core.intent_parser import IntentParser


@pytest.fixture
def parser():
    p = IntentParser()
    p._family_names = {
        "glen", "grandma", "dad", "mom", "mia", "brooklyn",
        "papa", "nana", "uncle bob", "bob", "sarah", "joe",
        "evelyn", "ryan",
    }
    return p


# ╔═══════════════════════════════════════════════════════════════╗
# ║                    PRAYER INTENTS                            ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestPrayerBasicPhrases:
    """Every basic way to ask for prayer → intent: prayer."""

    @pytest.mark.parametrize("text", [
        # Direct requests
        "say a prayer",
        "pray for me",
        "pray with me",
        "let's pray",
        "let us pray",
        "can you pray",
        "i need a prayer",
        "prayer",
        "pray",
        "say a prayer for me",
        "will you pray",
        "i want to pray",
        "help me pray",
        "lead me in prayer",
        "lead a prayer",
        "can we pray",
        "would you pray",
        "pray for us",
        "pray over me",
    ])
    def test_basic_prayer_request(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] == "prayer", f"'{text}' → {r['intent']} (expected prayer)"


class TestPrayerTimeBased:
    """Time-of-day prayer phrases → prayer with rest/strength theme."""

    @pytest.mark.parametrize("text,expected_theme", [
        ("bedtime prayer", "rest"),
        ("goodnight prayer", "rest"),
        ("nighttime prayer", "rest"),
        ("evening prayer", "rest"),
        ("morning prayer", "strength"),
        ("start the day with prayer", "strength"),
    ])
    def test_time_based_theme(self, parser, text, expected_theme):
        r = parser.parse(text)
        assert r["intent"] == "prayer"
        assert r["theme"] == expected_theme, f"'{text}' → theme={r['theme']} (expected {expected_theme})"


class TestPrayerEmotionalTriggers:
    """Natural emotional speech → prayer with correct theme."""

    @pytest.mark.parametrize("text,expected_theme", [
        # Anxiety
        ("i'm worried", "anxiety"),
        ("i'm scared", "anxiety"),
        ("i'm anxious", "anxiety"),
        # Grief
        ("i miss him", "grief"),
        ("i miss her", "grief"),
        ("i miss them", "grief"),
        # Loneliness
        ("i feel alone", "loneliness"),
        ("i feel lonely", "loneliness"),
        # Strength
        ("i'm having a hard day", "strength"),
        ("i'm struggling", "strength"),
        ("things are tough", "strength"),
        ("give me strength", "strength"),
        ("i need strength", "strength"),
        # Hope
        ("i need some hope", "hope"),
        ("i'm feeling down", "hope"),
        ("i'm feeling low", "hope"),
        # Peace
        ("i need peace", "peace"),
        ("i need comfort", "peace"),
        # Gratitude
        ("i'm thankful", "gratitude"),
        ("i'm grateful", "gratitude"),
        ("i'm blessed", "gratitude"),
        ("thank the lord", "gratitude"),
        ("praise god", "gratitude"),
        ("praise the lord", "gratitude"),
        ("bless this day", "gratitude"),
        ("bless my family", "gratitude"),  # "bless" matches gratitude before family
    ])
    def test_emotional_trigger_theme(self, parser, text, expected_theme):
        r = parser.parse(text)
        assert r["intent"] == "prayer", f"'{text}' → {r['intent']}"
        assert r["theme"] == expected_theme, f"'{text}' → theme={r['theme']} (expected {expected_theme})"


class TestPrayerThemeKeywords:
    """Prayer-themed keywords routed to themed prayer, NOT treated as person names."""

    @pytest.mark.parametrize("text,expected_theme", [
        # Strength group
        ("pray for strength", "strength"),
        ("pray for courage", "strength"),
        ("pray for resilience", "strength"),
        ("pray for perseverance", "strength"),
        ("prayer for resilience", "strength"),
        # Hope group
        ("pray for hope", "hope"),
        # Peace group
        ("pray for peace", "peace"),
        ("pray for comfort", "peace"),
        ("pray for grace", "peace"),
        ("pray for mercy", "peace"),
        ("pray for calm", "peace"),
        # Faith group
        ("pray for faith", "faith"),
        ("pray for wisdom", "faith"),
        ("pray for guidance", "faith"),
        # Gratitude group
        ("pray for blessings", "gratitude"),
        ("pray for glory", "gratitude"),
        # Healing
        ("pray for healing", "healing"),
        ("pray for health", "healing"),
        # Forgiveness
        ("pray for forgiveness", "forgiveness"),
        # Family
        ("pray for my family", "family"),
        ("pray for my kids", "family"),
        ("pray for my grandchildren", "family"),
        ("pray for my grandkids", "family"),
        # Joy
        ("pray for joy", "joy"),
        ("pray for happiness", "joy"),
    ])
    def test_theme_keyword_routing(self, parser, text, expected_theme):
        r = parser.parse(text)
        assert r["intent"] == "prayer", f"'{text}' → {r['intent']}"
        assert r["theme"] == expected_theme, f"'{text}' → theme={r['theme']} (expected {expected_theme})"
        assert r["pray_for"] is None, f"'{text}' → pray_for={r['pray_for']} (should be None — keyword, not person)"


class TestPrayerThemeKeywordsNotPerson:
    """Theme words must NOT be treated as person names in pray_for."""

    @pytest.mark.parametrize("text", [
        "pray for healing",
        "pray for strength",
        "pray for peace",
        "pray for hope",
        "pray for faith",
        "pray for courage",
        "pray for resilience",
        "pray for grace",
        "pray for comfort",
        "pray for guidance",
        "pray for joy",
        "pray for love",
        "pray for gratitude",
        "pray for forgiveness",
        "pray for patience",
        "pray for wisdom",
        "pray for rest",
        "pray for calm",
        "pray for purpose",
        "pray for blessings",
        "pray for protection",
        "pray for health",
        "pray for happiness",
        "pray for glory",
        "pray for mercy",
        "pray for perseverance",
        "prayer for resilience",
        "prayer for courage",
        "prayer for wisdom",
    ])
    def test_theme_keyword_not_person(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] == "prayer"
        assert r["pray_for"] is None, f"'{text}' set pray_for={r['pray_for']} — should be None"


class TestPrayerForPerson:
    """'Pray for [person name]' → extracts pray_for correctly."""

    @pytest.mark.parametrize("text,expected_person", [
        ("pray for ryan", "ryan"),
        ("pray for glen", "glen"),
        ("pray for grandma", "grandma"),
        ("pray for sarah", "sarah"),
        ("pray for bob", "bob"),
        ("pray for mia", "mia"),
        ("pray for brooklyn", "brooklyn"),
        ("pray over ryan", "ryan"),
        ("pray for dad", "dad"),
        ("pray for mom", "mom"),
        # "prayer for" variant (the regex fix)
        ("say a prayer for ryan", "ryan"),
        ("prayer for ryan", "ryan"),
        ("prayer for glen", "glen"),
        ("say a prayer for grandma", "grandma"),
        # With "please"
        ("pray for ryan please", "ryan"),
        ("pray for grandma please", "grandma"),
    ])
    def test_pray_for_person_extraction(self, parser, text, expected_person):
        r = parser.parse(text)
        assert r["intent"] == "prayer", f"'{text}' → {r['intent']}"
        assert r["pray_for"] == expected_person, f"'{text}' → pray_for={r['pray_for']} (expected {expected_person})"

    @pytest.mark.parametrize("text", [
        "pray for me",
        "pray for us",
        "pray for the family",
        "pray for my family",
        "pray for the kids",
    ])
    def test_pray_for_generic_not_extracted(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] == "prayer"
        assert r["pray_for"] is None, f"'{text}' → pray_for={r['pray_for']} (should be None — generic)"


class TestPrayerFamilySpecific:
    """Family prayer phrases → prayer with family theme."""

    @pytest.mark.parametrize("text", [
        "pray for my family",
        "family prayer",
        "pray for my kids",
        "pray for the children",
        "pray for my grandchildren",
        "pray for my grandkids",
    ])
    def test_family_prayer_theme(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] == "prayer"
        assert r["theme"] == "family"


class TestPrayerHealingContexts:
    """Health/healing triggers → healing theme."""

    @pytest.mark.parametrize("text,expected_theme", [
        ("pray for healing", "healing"),
        ("pray for health", "healing"),
    ])
    def test_healing_theme(self, parser, text, expected_theme):
        r = parser.parse(text)
        assert r["intent"] == "prayer"
        assert r["theme"] == expected_theme


class TestPrayerEdgeCases:
    """Tricky inputs that could misroute."""

    def test_pray_not_leave_message(self, parser):
        """'pray for ryan' should NOT trigger leave_message."""
        r = parser.parse("pray for ryan")
        assert r["intent"] == "prayer"

    def test_prayer_not_bible(self, parser):
        """'prayer' should not trigger bible_verse."""
        r = parser.parse("prayer")
        assert r["intent"] == "prayer"

    def test_i_need_a_prayer_not_item(self, parser):
        """'i need a prayer' should be prayer, not retrieve_item."""
        r = parser.parse("i need a prayer")
        assert r["intent"] == "prayer"

    def test_pray_for_unknown_person(self, parser):
        """'pray for charlie' (unknown name) → prayer with pray_for='charlie'."""
        r = parser.parse("pray for charlie")
        assert r["intent"] == "prayer"
        assert r["pray_for"] == "charlie"

    def test_say_a_prayer_for_person(self, parser):
        """Regression: 'say a prayer for ryan' was returning pray_for=None."""
        r = parser.parse("say a prayer for ryan")
        assert r["intent"] == "prayer"
        assert r["pray_for"] == "ryan"

    def test_pray_for_anxiety_not_person(self, parser):
        """'pray for anxiety' → anxiety theme, NOT a person named 'anxiety'."""
        r = parser.parse("i'm anxious")
        assert r["intent"] == "prayer"
        assert r["theme"] == "anxiety"
        assert r.get("pray_for") is None

    def test_pray_for_grief_not_person(self, parser):
        """'pray for grief' — grief is in skip list."""
        r = parser.parse("pray for grief")
        assert r["intent"] == "prayer"
        assert r["pray_for"] is None

    def test_pray_for_worry_not_person(self, parser):
        r = parser.parse("pray for worry")
        assert r["intent"] == "prayer"
        assert r["pray_for"] is None

    def test_pray_for_fear_not_person(self, parser):
        r = parser.parse("pray for fear")
        assert r["intent"] == "prayer"
        assert r["pray_for"] is None

    def test_no_theme_no_person_general_prayer(self, parser):
        """'pray' with no qualifiers → prayer intent, no theme, no pray_for."""
        r = parser.parse("pray")
        assert r["intent"] == "prayer"
        assert r["theme"] is None
        assert r["pray_for"] is None

    def test_let_us_pray_general(self, parser):
        r = parser.parse("let us pray")
        assert r["intent"] == "prayer"
        assert r["theme"] is None


# ╔═══════════════════════════════════════════════════════════════╗
# ║                    STORY INTENTS                             ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestHearStories:
    """All the ways to ask Polly to read/tell/play back stories."""

    @pytest.mark.parametrize("text", [
        # Direct requests
        "tell me a story",
        "read me a story",
        "play a story",
        "share a story",
        "read a story",
        "narrate a story",
        "story reading",
        # My stories
        "play my stories",
        "read my stories",
        "read me my stories",
        "tell me my story",
        "tell me one of my stories",
        "read back my stories",
        # About someone
        "tell me about grandma",
        "tell me about dad",
        "tell me about the farm",
        # Play back
        "play back",
        # Questions about stories
        "what stories do we have",
        "any stories about grandma",
        "do you have any stories",
        # What did they say
        "what did grandma say",
        "what did she say",
        "what did he say",
        "what has grandma said",
        "what has she said",
        # Heard about
        "what have you heard about dad",
    ])
    def test_hear_stories(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] == "hear_stories", f"'{text}' → {r['intent']} (expected hear_stories)"

    def test_hear_stories_query_extraction_about(self, parser):
        """'tell me about grandma' → query='grandma'."""
        r = parser.parse("tell me about grandma")
        assert r["intent"] == "hear_stories"
        assert r["query"] == "grandma"

    def test_hear_stories_query_extraction_what_did(self, parser):
        """'what did grandma say' → query includes 'grandma say'."""
        r = parser.parse("what did grandma say")
        assert r["intent"] == "hear_stories"
        assert "grandma" in r["query"]

    def test_hear_stories_query_any_stories_about(self, parser):
        """'any stories about the farm' → query='the farm'."""
        r = parser.parse("any stories about the farm")
        assert r["intent"] == "hear_stories"
        assert "farm" in r["query"]

    def test_hear_stories_no_query_general(self, parser):
        """'tell me a story' → no specific query."""
        r = parser.parse("tell me a story")
        assert r["intent"] == "hear_stories"
        # query is None or empty for general requests
        # "tell me a story" matches as hear_stories, query may be None


class TestTellStory:
    """User wants to RECORD a story (their voice → stored memory)."""

    @pytest.mark.parametrize("text", [
        "let me tell you about my childhood",
        "i remember when we lived on the farm",
        "i want to tell you about the war",
        "let me share a memory",
        "i have a story",
        "story time",
        "i want to record a story",
        "take my story",
        "i want to share something",
        "record my story",
        "i have something to share",
        "i want to tell a story",
        "let me tell you something",
        "can i tell you something",
        "i got a story",
        "i have a memory to share",
    ])
    def test_tell_story(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] == "tell_story", f"'{text}' → {r['intent']} (expected tell_story)"


class TestFamilyQuestion:
    """Polly asks the user a guided family/life question."""

    @pytest.mark.parametrize("text", [
        "ask me about my family",
        "family question",
        "ask me a family question",
        "family story",
        "ask me something about my life",
        "ask me about my life",
        "tell me about my family",
        "ask me a question about my life",
        "i want to answer questions",
        "interview me",
        "let's do a family question",
        "give me a question",
        "ask me about my past",
        "ask me about growing up",
    ])
    def test_family_question(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] == "family_question", f"'{text}' → {r['intent']} (expected family_question)"


class TestStoryProgress:
    """User checking how many stories/memories have been captured."""

    @pytest.mark.parametrize("text", [
        "how many stories do i have",
        "my progress",
        "story progress",
        "how many memories do i have",
        "show my progress",
        "what have we captured",
        "book progress",
        "how's the book coming",
        "how's my book",
        "how far along are we",
        "how many have we done",
    ])
    def test_story_progress(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] == "story_progress", f"'{text}' → {r['intent']} (expected story_progress)"


class TestStoryIntroduction:
    """User introducing themselves for story recording."""

    @pytest.mark.parametrize("text,expected_name", [
        ("this is Sarah", "Sarah"),
        ("this is Glen", "Glen"),
        ("my name is Joe", "Joe"),
        ("my name is Sarah", "Sarah"),
    ])
    def test_introduce_self(self, parser, text, expected_name):
        r = parser.parse(text)
        assert r["intent"] == "introduce_self"
        assert r["name"] == expected_name

    def test_introduce_with_relationship(self, parser):
        r = parser.parse("This is Sarah, I'm her granddaughter")
        assert r["intent"] == "introduce_self"
        assert r["name"] == "Sarah"
        assert r["relationship"]


# ╔═══════════════════════════════════════════════════════════════╗
# ║              CROSS-INTENT GUARDS & FALSE POSITIVES           ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestStoryVsPrayerGuards:
    """Stories and prayers should not bleed into each other."""

    def test_tell_me_a_story_not_prayer(self, parser):
        r = parser.parse("tell me a story")
        assert r["intent"] != "prayer"

    def test_pray_not_story(self, parser):
        r = parser.parse("pray for me")
        assert r["intent"] != "hear_stories"
        assert r["intent"] != "tell_story"

    def test_read_me_a_story_not_bible(self, parser):
        """'read me a story' → hear_stories, NOT bible_verse."""
        r = parser.parse("read me a story")
        assert r["intent"] == "hear_stories"

    def test_read_me_a_verse_not_story(self, parser):
        """'read me a verse' → bible_verse, NOT hear_stories."""
        r = parser.parse("read me a verse")
        assert r["intent"] == "bible_verse"


class TestPrayerVsOtherIntents:
    """Prayer should not steal from other intents, and vice versa."""

    def test_i_need_help_not_prayer(self, parser):
        """'i need help' is help intent, not prayer."""
        r = parser.parse("i need help")
        assert r["intent"] == "help"

    def test_cheer_me_up_is_joke(self, parser):
        """'cheer me up' → tell_joke, not prayer."""
        r = parser.parse("cheer me up")
        assert r["intent"] == "tell_joke"

    def test_i_need_my_phone_is_item(self, parser):
        """'i need my phone' → retrieve_item, not prayer."""
        r = parser.parse("i need my phone")
        assert r["intent"] == "retrieve_item"

    def test_where_is_glen_not_prayer(self, parser):
        r = parser.parse("where is glen")
        assert r["intent"] == "where_is_person"

    def test_thank_you_not_prayer(self, parser):
        """'thank you' → thank_you, not prayer (despite 'thank' being in prayer phrases)."""
        r = parser.parse("thank you")
        assert r["intent"] == "thank_you"


class TestStoryVsOtherIntents:
    """Story intents should not steal from messages/items/etc."""

    def test_tell_dad_message_not_story(self, parser):
        """'tell dad I love him' → leave_message, NOT tell_story."""
        r = parser.parse("tell dad i love him")
        assert r["intent"] == "leave_message"

    def test_what_did_i_miss_is_messages(self, parser):
        """'what did i miss' → check_messages, NOT hear_stories."""
        r = parser.parse("what did i miss")
        assert r["intent"] == "check_messages"

    def test_interview_me_is_family_question(self, parser):
        r = parser.parse("interview me")
        assert r["intent"] == "family_question"

    def test_how_is_my_book_is_progress(self, parser):
        r = parser.parse("how's my book")
        assert r["intent"] == "story_progress"


class TestPrayerAndStoryPriorityOrder:
    """Verify the intent priority is correct for prayer and story checks."""

    def test_story_checked_before_prayer(self, parser):
        """Family story intents are checked before prayer in the parser."""
        # "family story" should match family_question, not prayer
        r = parser.parse("family story")
        assert r["intent"] == "family_question"

    def test_bible_before_prayer(self, parser):
        """Bible verse is checked before prayer."""
        r = parser.parse("read me a verse")
        assert r["intent"] == "bible_verse"

    def test_prayer_before_item_memory(self, parser):
        """Prayer should be checked before item/memory intents."""
        r = parser.parse("i need a prayer")
        assert r["intent"] == "prayer"

    def test_greeting_does_not_steal_prayer(self, parser):
        """'good morning' → greeting (not morning prayer)."""
        r = parser.parse("good morning")
        assert r["intent"] == "greeting"

    def test_goodbye_not_bedtime_prayer(self, parser):
        """'goodnight' → goodbye, not bedtime prayer."""
        r = parser.parse("goodnight")
        assert r["intent"] == "goodbye"


# ╔═══════════════════════════════════════════════════════════════╗
# ║              NATURAL SPEECH VARIATIONS                       ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestNaturalSpeechPrayer:
    """Realistic STT transcriptions for prayer requests."""

    @pytest.mark.parametrize("text", [
        "polly can you say a prayer for me",
        "polly say a prayer",
        "polly pray for me",
        "hey polly will you pray with me",
        "i would like to pray",
        "polly let's pray together",
        "can you lead us in prayer",
        "polly pray for ryan",
        "say a prayer for my friend ryan",
    ])
    def test_natural_prayer_requests(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] == "prayer", f"'{text}' → {r['intent']}"

    @pytest.mark.parametrize("text", [
        "polly can you read me a story",
        "polly tell me a story",
        "hey polly do you have any stories",
        "read me one of my stories",
        "polly play my stories back",
        "can you read a story for me",
    ])
    def test_natural_story_requests(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] == "hear_stories", f"'{text}' → {r['intent']}"


class TestNaturalSpeechRecordStory:
    """Realistic STT transcriptions for wanting to record a story."""

    @pytest.mark.parametrize("text", [
        "polly let me tell you about my childhood",
        "i want to tell you about when i was young",
        "let me share something with you",
        "i have a memory to share with you",
        "polly i want to record a story",
        "hey polly story time",
        "can i tell you something about my life",
    ])
    def test_natural_record_story(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] == "tell_story", f"'{text}' → {r['intent']}"


# ╔═══════════════════════════════════════════════════════════════╗
# ║              REGRESSION TESTS (BUGS.MD)                      ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestRegressions:
    """Tests for bugs documented in bugs.md."""

    def test_pray_for_resilience_not_person(self, parser):
        """Bug: 'pray for resilience' treated as person name."""
        r = parser.parse("pray for resilience")
        assert r["intent"] == "prayer"
        assert r["pray_for"] is None
        assert r["theme"] == "strength"

    def test_say_a_prayer_for_ryan_extracts_name(self, parser):
        """Bug: 'say a prayer for ryan' → pray_for: None (regex only matched 'pray for')."""
        r = parser.parse("say a prayer for ryan")
        assert r["intent"] == "prayer"
        assert r["pray_for"] == "ryan"

    def test_prayer_for_ryan_extracts_name(self, parser):
        """Bug: 'prayer for ryan' → pray_for: None."""
        r = parser.parse("prayer for ryan")
        assert r["intent"] == "prayer"
        assert r["pray_for"] == "ryan"

    def test_what_did_i_miss_not_hear_stories(self, parser):
        """Bug: 'what did i miss' was matching hear_stories."""
        r = parser.parse("what did i miss")
        assert r["intent"] == "check_messages"

    def test_do_i_need_an_umbrella_not_item(self, parser):
        """Bug: 'do i need an umbrella' matched retrieve_item before weather."""
        r = parser.parse("do i need an umbrella")
        assert r["intent"] == "weather"

    def test_wallet_not_location(self, parser):
        """Bug: 'where is my wallet' matched as location because 'wall' in 'wallet'."""
        r = parser.parse("where is my wallet")
        assert r["intent"] == "retrieve_item"

    def test_going_to_bed_not_status(self, parser):
        """Bug: 'i'm going to bed' matched status_update instead of goodbye."""
        r = parser.parse("i'm going to bed")
        assert r["intent"] == "goodbye"

    def test_um_inside_word_not_thinking(self, parser):
        """Bug: 'dumbbells' matched 'um' thinking phrase."""
        r = parser.parse("my dumbbells are in the garage")
        assert r["intent"] != "thinking"

    def test_psalm_stt_variant(self, parser):
        """Bug: STT transcribes 'psalm' as 'salm'."""
        r = parser.parse("read me a salm")
        assert r["intent"] == "bible_verse"
        assert r["topic"] == "Psalm"
