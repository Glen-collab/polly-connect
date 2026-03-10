"""
Test Suite A - Core Voice Pipeline
===================================
Systematic test of all voice intents a family member would encounter.
Run: python -m pytest tests/test_A.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from server.core.intent_parser import IntentParser


@pytest.fixture
def parser():
    p = IntentParser()
    # Simulate a family tree with common names
    p._family_names = {
        "glen", "grandma", "dad", "mom", "mia", "brooklyn",
        "papa", "nana", "uncle bob", "bob", "sarah", "joe",
    }
    return p


# ─── GREETINGS & GOODBYES ───

class TestGreetings:
    @pytest.mark.parametrize("text", [
        "hello polly",
        "hi polly",
        "good morning",
        "good afternoon",
        "good evening",
        "hey there",
        "howdy",
    ])
    def test_greeting(self, parser, text):
        assert parser.parse(text)["intent"] == "greeting"

    @pytest.mark.parametrize("text", [
        "goodbye polly",
        "bye bye",
        "see you later",
        "good night",
        "goodnight polly",
        "nighty night",
        "i'm going to bed",
    ])
    def test_goodbye(self, parser, text):
        assert parser.parse(text)["intent"] == "goodbye"

    @pytest.mark.parametrize("text", [
        "thank you",
        "thanks polly",
        "thanks so much",
        "appreciate it",
        "you're the best",
    ])
    def test_thank_you(self, parser, text):
        assert parser.parse(text)["intent"] == "thank_you"


# ─── JOKES ───

class TestJokes:
    @pytest.mark.parametrize("text", [
        "tell me a joke",
        "make me laugh",
        "say something funny",
        "i need a laugh",
        "cheer me up",
        "got any jokes",
        "tell me another joke",
        "another joke",
        "joke please",
    ])
    def test_tell_joke(self, parser, text):
        assert parser.parse(text)["intent"] == "tell_joke"

    @pytest.mark.parametrize("text", [
        "tell me a kid joke",
        "tell me a fart joke",
        "tell me a poop joke",
        "tell me a dinosaur joke",
        "tell me a unicorn joke",
        "potty joke",
        "silly joke",
        "tell me a gross joke",
        "joke for kids",
        "got any kid jokes",
    ])
    def test_tell_kid_joke(self, parser, text):
        assert parser.parse(text)["intent"] == "tell_kid_joke"

    def test_kid_joke_before_regular(self, parser):
        """'tell me a kid joke' contains 'tell me a joke' — kid must win."""
        r = parser.parse("tell me a kid joke")
        assert r["intent"] == "tell_kid_joke"


# ─── BIBLE VERSES ───

class TestBible:
    @pytest.mark.parametrize("text", [
        "read me a bible verse",
        "bible verse",
        "read me a verse about hope",
        "verse about love",
        "read me a psalm",
        "read me a proverb",
        "give me some scripture",
        "what does the bible say",
        "verse of the day",
        "daily bible verse",
        "today's verse",
    ])
    def test_bible_verse(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] == "bible_verse"

    def test_bible_topic_extraction(self, parser):
        r = parser.parse("read me a verse about strength")
        assert r["intent"] == "bible_verse"
        assert r["topic"] == "strength"

    def test_bible_psalm(self, parser):
        r = parser.parse("read me a psalm")
        assert r["topic"] == "Psalm"

    def test_bible_proverb(self, parser):
        r = parser.parse("read me a proverb")
        assert r["topic"] == "Proverb"


# ─── WEATHER ───

class TestWeather:
    @pytest.mark.parametrize("text", [
        "what's the weather",
        "what is the weather",
        "how's the weather",
        "what's it like outside",
        "is it going to rain",
        "do i need an umbrella",
        "what's the forecast",
        "weather today",
        "what's the temperature",
    ])
    def test_weather(self, parser, text):
        assert parser.parse(text)["intent"] == "weather"


# ─── TIME & DATE ───

class TestTimeDate:
    @pytest.mark.parametrize("text", [
        "what time is it",
        "what's the time",
        "do you have the time",
        "tell me the time",
    ])
    def test_tell_time(self, parser, text):
        assert parser.parse(text)["intent"] == "tell_time"

    @pytest.mark.parametrize("text", [
        "what day is it",
        "what's today's date",
        "what is today",
        "what day of the week is it",
    ])
    def test_tell_date(self, parser, text):
        assert parser.parse(text)["intent"] == "tell_date"


# ─── MEDICATIONS ───

class TestMedications:
    @pytest.mark.parametrize("text", [
        "what are my medications",
        "what medications do i take",
        "my pills",
        "my meds",
        "i took my pills",
        "i took my medicine",
        "did i take my meds",
        "meds taken",
    ])
    def test_medication(self, parser, text):
        assert parser.parse(text)["intent"] == "medication"


# ─── ITEM MEMORY ───

class TestItemMemory:
    @pytest.mark.parametrize("text,item,location", [
        ("my keys are on the counter", "keys", "counter"),
        ("my glasses are in the drawer", "glasses", "drawer"),
        ("the remote is on the coffee table", "remote", "coffee table"),
        ("i put my wallet on the dresser", "wallet", "dresser"),
    ])
    def test_store_item(self, parser, text, item, location):
        r = parser.parse(text)
        assert r["intent"] == "store"
        assert r["item"] == item
        assert r["location"] == location

    @pytest.mark.parametrize("text,item", [
        ("where are my keys", "keys"),
        ("where did i put my glasses", "glasses"),
        ("where is my wallet", "wallet"),
        ("i need my phone", "phone"),
    ])
    def test_retrieve_item(self, parser, text, item):
        r = parser.parse(text)
        assert r["intent"] == "retrieve_item"
        assert r["item"] == item

    @pytest.mark.parametrize("text", [
        "what's in the drawer",
        "what's on the counter",
        "what do i have in the toolbox",
    ])
    def test_location_query(self, parser, text):
        assert parser.parse(text)["intent"] == "retrieve_location"

    @pytest.mark.parametrize("text", [
        "forget about the keys",
        "delete the glasses",
        "remove the wallet",
    ])
    def test_delete_item(self, parser, text):
        assert parser.parse(text)["intent"] == "delete"


# ─── MESSAGE BOARD ───

class TestMessageBoard:
    @pytest.mark.parametrize("text", [
        "any messages",
        "check messages",
        "do i have messages",
        "read my messages",
        "what did i miss",
        "anything on the board",
    ])
    def test_check_messages(self, parser, text):
        assert parser.parse(text)["intent"] == "check_messages"

    @pytest.mark.parametrize("text", [
        "clear the board",
        "clear messages",
        "delete all messages",
        "wipe the board",
    ])
    def test_clear_messages(self, parser, text):
        assert parser.parse(text)["intent"] == "clear_messages"

    @pytest.mark.parametrize("text,person", [
        ("dad is home", "dad"),
        ("mom is back", "mom"),
        ("glen is here", "glen"),
    ])
    def test_person_home(self, parser, text, person):
        r = parser.parse(text)
        assert r["intent"] == "person_home"
        assert r["person"].lower() == person

    @pytest.mark.parametrize("text", [
        "tell dad i'm going to the store",
        "tell mom i love her",
        "leave a message for grandma hi grandma",
    ])
    def test_leave_message(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] == "leave_message"
        assert r["person"]
        assert r["message"]

    @pytest.mark.parametrize("text,person", [
        ("where is dad", "dad"),
        ("where's mom", "mom"),
        ("where is glen", "glen"),
    ])
    def test_where_is_person(self, parser, text, person):
        r = parser.parse(text)
        assert r["intent"] == "where_is_person"
        assert r["person"].lower() == person


# ─── STATUS UPDATES ───

class TestStatusUpdates:
    @pytest.mark.parametrize("text", [
        "dad is going to work",
        "dad is going for a walk",
        "mom is headed to the store",
        "glen is off to the gym",
        "dad went to work",
        "mom is leaving for the doctor",
        "dad is out for a run",
        "dad went for a bike ride",
    ])
    def test_other_person_status(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] == "status_update"
        assert r["person"]
        assert r["status"]

    @pytest.mark.parametrize("text", [
        "i'm going to the store",
        "i'm headed to work",
        "i'm going for a walk",
        "i'm off to the gym",
        "i'm out for a run",
    ])
    def test_self_status(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] == "status_update"
        assert r["person"] is None  # self-report
        assert r["status"]

    def test_going_for_a_walk(self, parser):
        """Regression: 'dad is going for a walk' was hitting unknown."""
        r = parser.parse("dad is going for a walk")
        assert r["intent"] == "status_update"
        assert "walk" in r["status"]


# ─── FAMILY STORIES ───

class TestFamilyStories:
    @pytest.mark.parametrize("text", [
        "ask me a family question",
        "family question",
        "interview me",
        "ask me about my life",
        "ask me about my past",
        "ask me about growing up",
    ])
    def test_family_question(self, parser, text):
        assert parser.parse(text)["intent"] == "family_question"

    @pytest.mark.parametrize("text", [
        "let me tell you about my childhood",
        "i remember when we lived on the farm",
        "record my story",
        "i have a story",
        "story time",
    ])
    def test_tell_story(self, parser, text):
        assert parser.parse(text)["intent"] == "tell_story"

    def test_tell_me_a_story_is_hear(self, parser):
        """'tell me a story' means user wants to HEAR a story, not record one."""
        assert parser.parse("tell me a story")["intent"] == "hear_stories"

    @pytest.mark.parametrize("text", [
        "how many stories do i have",
        "my progress",
        "story progress",
        "how's my book",
        "how far along are we",
    ])
    def test_story_progress(self, parser, text):
        assert parser.parse(text)["intent"] == "story_progress"


# ─── NAVIGATION ───

class TestNavigation:
    @pytest.mark.parametrize("text", [
        "repeat",
        "say that again",
        "what did you say",
        "i didn't hear you",
        "huh",
        "pardon",
        "ask me again",
    ])
    def test_repeat(self, parser, text):
        assert parser.parse(text)["intent"] == "repeat"

    @pytest.mark.parametrize("text", [
        "skip",
        "next question",
        "i don't know",
        "pass",
        "ask me something else",
        "different question",
    ])
    def test_skip(self, parser, text):
        assert parser.parse(text)["intent"] == "skip"

    @pytest.mark.parametrize("text", [
        "stop",
        "i'm done",
        "that's enough",
        "no more",
        "enough for today",
    ])
    def test_stop(self, parser, text):
        assert parser.parse(text)["intent"] == "stop"

    @pytest.mark.parametrize("text", [
        "help",
        "what can you do",
        "what are you",
        "i need help",
    ])
    def test_help(self, parser, text):
        assert parser.parse(text)["intent"] == "help"


# ─── IDENTITY ───

class TestIdentity:
    def test_introduce_self(self, parser):
        r = parser.parse("This is Sarah")
        assert r["intent"] == "introduce_self"
        assert r["name"] == "Sarah"

    def test_my_name_is(self, parser):
        r = parser.parse("My name is Joe")
        assert r["intent"] == "introduce_self"
        assert r["name"] == "Joe"

    @pytest.mark.parametrize("text,name", [
        ("who is mia", "mia"),
        ("who's brooklyn", "brooklyn"),
        ("who is uncle bob", "uncle bob"),
    ])
    def test_who_is(self, parser, text, name):
        r = parser.parse(text)
        assert r["intent"] == "who_is"
        assert r["name"] == name


# ─── FALSE POSITIVE GUARDS ───

class TestFalsePositives:
    def test_umbrella_not_item_query(self, parser):
        """'do i need an umbrella' should be weather, not retrieve_item."""
        assert parser.parse("do i need an umbrella")["intent"] == "weather"

    def test_tell_me_joke_not_leave_message(self, parser):
        """'tell me a joke' should not trigger leave_message."""
        assert parser.parse("tell me a joke")["intent"] == "tell_joke"

    def test_this_is_great_not_intro(self, parser):
        """'this is great' should not trigger introduce_self."""
        assert parser.parse("this is great")["intent"] != "introduce_self"

    def test_brooklyn_status_not_store(self, parser):
        """'brooklyn is going poop in the bathroom' — person status, not item store."""
        r = parser.parse("brooklyn is going poop in the bathroom")
        assert r["intent"] != "store"

    def test_empty_input(self, parser):
        assert parser.parse("")["intent"] == "unknown"

    def test_random_gibberish(self, parser):
        assert parser.parse("asdfghjkl qwerty")["intent"] == "unknown"

    def test_um_inside_word(self, parser):
        """'dumbbells' should NOT match the 'um' thinking phrase."""
        r = parser.parse("my dumbbells are in the garage")
        assert r["intent"] != "thinking"

    def test_it_is_home_not_person(self, parser):
        """'it is home' should NOT match person_home."""
        r = parser.parse("it is home")
        assert r["intent"] != "person_home"

    def test_kid_joke_wins_over_regular(self, parser):
        """Kid joke intents must be checked before regular joke."""
        assert parser.parse("tell me a silly joke")["intent"] == "tell_kid_joke"


# ─── CONTRACTION NORMALIZATION ───

class TestContractions:
    def test_whats_the_weather(self, parser):
        """STT might drop apostrophe: 'whats the weather'."""
        assert parser.parse("whats the weather")["intent"] == "weather"

    def test_whats_the_time(self, parser):
        assert parser.parse("whats the time")["intent"] == "tell_time"

    def test_whats_todays_date(self, parser):
        assert parser.parse("whats todays date")["intent"] == "tell_date"

    def test_im_going_to_the_store(self, parser):
        r = parser.parse("im going to the store")
        assert r["intent"] == "status_update"

    def test_im_done(self, parser):
        assert parser.parse("im done")["intent"] == "stop"
