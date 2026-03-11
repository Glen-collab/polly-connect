"""
Test Suite C - Story Queries, Prayer Queue, Narrative Caching & Squawk Safety
==============================================================================
Tests for Phase 31 features:
  - Story topic/person query extraction ("tell me a story about X")
  - New story phrases ("say a story", "give me a story", etc.)
  - Prayer request auto-delete queue behavior
  - Story narrative caching (save/keep/replay)
  - Squawk/chatter does NOT interfere with intent parsing
Run: python -m pytest tests/test_C.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch
from server.core.intent_parser import IntentParser


@pytest.fixture
def parser():
    p = IntentParser()
    p._family_names = {
        "glen", "grandma", "dad", "mom", "mia", "brooklyn",
        "papa", "nana", "uncle bob", "bob", "sarah", "joe",
        "evelyn", "ryan", "uncle johnnie", "johnnie",
    }
    return p


@pytest.fixture
def db():
    """Create a real in-memory database for integration tests."""
    from server.core.database import PollyDB as Database
    d = Database(":memory:")
    # Create a tenant
    d.create_tenant("Test Family")
    return d


# ╔═══════════════════════════════════════════════════════════════╗
# ║              STORY QUERY EXTRACTION                          ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestStoryQueryExtraction:
    """'Tell me a story about X' should extract X as query."""

    @pytest.mark.parametrize("text,expected_query", [
        ("tell me a story about uncle johnnie", "uncle johnnie"),
        ("tell me a story about the farm", "the farm"),
        ("tell me a story about when i was young", "when i was young"),
        ("say a story about fishing", "fishing"),
        ("give me a story about mom", "mom"),
        ("read me a story about christmas", "christmas"),
        ("share a story about the lake", "the lake"),
        ("any stories about grandpa", "grandpa"),
        ("do you have any stories about the war", "the war"),
        ("can you tell me a story about uncle johnnie when i was young",
         "uncle johnnie when i was young"),
        ("play a story about dad", "dad"),
        ("i want to hear a story about growing up", "growing up"),
        ("got any stories about the old house", "the old house"),
    ])
    def test_story_with_topic(self, parser, text, expected_query):
        r = parser.parse(text)
        assert r["intent"] == "hear_stories", f"'{text}' -> {r['intent']}"
        assert r.get("query") == expected_query, \
            f"'{text}' -> query={r.get('query')!r} (expected {expected_query!r})"

    @pytest.mark.parametrize("text", [
        "tell me a story about",
        "say a story about",
    ])
    def test_story_about_with_no_topic_gives_none(self, parser, text):
        """If user says 'about' but nothing after, query should be None."""
        r = parser.parse(text)
        assert r["intent"] == "hear_stories"
        assert r.get("query") is None


class TestStoryNoQuery:
    """Generic story requests should have query=None."""

    @pytest.mark.parametrize("text", [
        "tell me a story",
        "say a story",
        "give me a story",
        "read me a story",
        "share a story",
        "hear a story",
        "let's hear a story",
        "i want to hear a story",
        "can you tell me a story",
        "do you have a story",
        "got any stories",
        "narrate a story",
        "play a story",
        "read a story",
        "play my stories",
    ])
    def test_generic_story_no_query(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] == "hear_stories", f"'{text}' -> {r['intent']}"
        assert r.get("query") is None, f"'{text}' -> unexpected query={r.get('query')!r}"


# ╔═══════════════════════════════════════════════════════════════╗
# ║              NEW STORY PHRASES                               ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestNewStoryPhrases:
    """All new story trigger phrases should map to hear_stories."""

    @pytest.mark.parametrize("text", [
        "say a story",
        "give me a story",
        "got any stories",
        "hear a story",
        "let's hear a story",
        "i want to hear a story",
        "i'd like to hear a story",
        "let me hear a story",
        "can you tell me a story",
        "do you have a story",
    ])
    def test_new_phrases(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] == "hear_stories", f"'{text}' -> {r['intent']}"


# ╔═══════════════════════════════════════════════════════════════╗
# ║              STORY vs TELL STORY GUARDS                      ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestStoryVsTellStoryGuards:
    """Ensure 'hear' vs 'tell' story intents don't collide."""

    @pytest.mark.parametrize("text,expected", [
        ("i got a story", "tell_story"),
        ("i have a story to tell", "tell_story"),
        ("i want to tell you a story", "tell_story"),
        ("let me tell you something", "tell_story"),
        ("tell me a story", "hear_stories"),
        ("can you tell me a story", "hear_stories"),
        ("tell me a story about the lake", "hear_stories"),
    ])
    def test_hear_vs_tell(self, parser, text, expected):
        r = parser.parse(text)
        assert r["intent"] == expected, f"'{text}' -> {r['intent']} (expected {expected})"


# ╔═══════════════════════════════════════════════════════════════╗
# ║              STORY vs PRAYER GUARDS (new phrases)            ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestNewPhrasesVsPrayer:
    """New story phrases should NOT trigger prayer intent."""

    @pytest.mark.parametrize("text", [
        "say a story",
        "say a story about mom",
        "give me a story about the church",
    ])
    def test_story_not_prayer(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] == "hear_stories", \
            f"'{text}' -> {r['intent']} (should be hear_stories, not prayer)"

    @pytest.mark.parametrize("text", [
        "say a prayer",
        "say a prayer for me",
        "say a prayer for ryan",
    ])
    def test_prayer_not_story(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] == "prayer", \
            f"'{text}' -> {r['intent']} (should be prayer, not hear_stories)"


# ╔═══════════════════════════════════════════════════════════════╗
# ║              SQUAWK / CHATTER DOES NOT INTERFERE             ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestSquawkNoInterference:
    """Squawk/chatter audio is handled separately in audio.py.
    Ensure that if STT accidentally transcribes squawk sounds,
    common misrecognitions do NOT trigger real intents."""

    @pytest.mark.parametrize("text", [
        # Common STT misrecognitions of parrot squawks
        "",
        "ah",
        "uh",
        "hmm",
        "squawk",
        "bawk",
        "brawk",
        "caw caw",
        "polly want a cracker",
        "awk",
        # Background noise / silence
        "the",
        "a",
        "uh huh",
    ])
    def test_squawk_noise_is_unknown_or_ignored(self, parser, text):
        r = parser.parse(text)
        # Should be unknown/greeting at worst, never a destructive intent
        assert r["intent"] not in (
            "prayer", "hear_stories", "tell_story", "medication",
            "store_item", "delete_item", "bible_verse",
        ), f"Squawk noise '{text}' triggered {r['intent']}!"

    @pytest.mark.parametrize("text", [
        # Real commands should still work fine after squawk
        "hey polly what time is it",
        "hey polly tell me a story",
        "hey polly say a prayer",
        "hey polly tell me a joke",
    ])
    def test_real_commands_still_work(self, parser, text):
        r = parser.parse(text)
        assert r["intent"] != "unknown", \
            f"Real command '{text}' was classified as unknown"


# ╔═══════════════════════════════════════════════════════════════╗
# ║              PRAYER REQUEST QUEUE (auto-delete)              ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestPrayerRequestQueue:
    """Prayer requests are auto-deleted after being used."""

    def test_add_and_get_prayer_requests(self, db):
        db.add_prayer_request("Aunt Susan", "healing from surgery", tenant_id=1)
        db.add_prayer_request("Uncle Bob", "strength", tenant_id=1)
        requests = db.get_prayer_requests(1, active_only=True)
        assert len(requests) == 2
        names = {r["name"] for r in requests}
        assert "Aunt Susan" in names
        assert "Uncle Bob" in names

    def test_delete_prayer_request(self, db):
        rid = db.add_prayer_request("Test Person", "test", tenant_id=1)
        db.delete_prayer_request(rid)
        requests = db.get_prayer_requests(1, active_only=True)
        assert len(requests) == 0

    def test_queue_behavior_simulation(self, db):
        """Simulate: add 3 requests, 'use' them (delete), verify gone."""
        ids = []
        for name in ["Person A", "Person B", "Person C"]:
            ids.append(db.add_prayer_request(name, tenant_id=1))

        before = db.get_prayer_requests(1, active_only=True)
        assert len(before) == 3

        # Simulate prayer queue: delete used requests (first 3)
        for pr in before[:3]:
            db.delete_prayer_request(pr["id"])

        after = db.get_prayer_requests(1, active_only=True)
        assert len(after) == 0

    def test_queue_with_more_than_three(self, db):
        """If 5 requests exist, only first 3 are used and deleted."""
        for i in range(5):
            db.add_prayer_request(f"Person {i}", tenant_id=1)

        all_req = db.get_prayer_requests(1, active_only=True)
        assert len(all_req) == 5

        # Simulate prayer: only first 3 are included in prompt
        used = all_req[:3]
        for pr in used:
            db.delete_prayer_request(pr["id"])

        remaining = db.get_prayer_requests(1, active_only=True)
        assert len(remaining) == 2


# ╔═══════════════════════════════════════════════════════════════╗
# ║              STORY NARRATIVE CACHING                         ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestNarrativeCaching:
    """Story narratives are saved, kept, edited, and replayed."""

    def test_save_narrative(self, db):
        nid = db.save_narrative(1, "Once upon a time...",
                                attribution="Glen shared this one.",
                                story_ids=[3, 7], query=None)
        assert nid > 0

    def test_get_narratives(self, db):
        db.save_narrative(1, "Story A", story_ids=[1])
        db.save_narrative(1, "Story B", story_ids=[2])
        all_n = db.get_narratives(1)
        assert len(all_n) == 2

    def test_draft_status_default(self, db):
        db.save_narrative(1, "Draft story", story_ids=[1])
        narrs = db.get_narratives(1)
        assert narrs[0]["status"] == "draft"

    def test_keep_narrative(self, db):
        nid = db.save_narrative(1, "Original text", story_ids=[1])
        db.update_narrative(nid, status="kept")
        n = db.get_narrative(nid)
        assert n["status"] == "kept"
        assert n["narrative"] == "Original text"

    def test_edit_and_keep_narrative(self, db):
        nid = db.save_narrative(1, "GPT said this", story_ids=[5, 6])
        db.update_narrative(nid, narrative="I edited this", status="kept")
        n = db.get_narrative(nid)
        assert n["status"] == "kept"
        assert n["narrative"] == "I edited this"

    def test_filter_by_status(self, db):
        db.save_narrative(1, "Draft one", story_ids=[1])
        nid = db.save_narrative(1, "Kept one", story_ids=[2])
        db.update_narrative(nid, status="kept")

        drafts = db.get_narratives(1, status="draft")
        kept = db.get_narratives(1, status="kept")
        assert len(drafts) == 1
        assert len(kept) == 1
        assert drafts[0]["narrative"] == "Draft one"
        assert kept[0]["narrative"] == "Kept one"

    def test_delete_narrative(self, db):
        nid = db.save_narrative(1, "To be deleted", story_ids=[1])
        db.delete_narrative(nid)
        assert db.get_narrative(nid) is None

    def test_story_ids_stored_as_csv(self, db):
        nid = db.save_narrative(1, "Multi-story", story_ids=[3, 7, 12])
        n = db.get_narrative(nid)
        assert n["story_ids"] == "3,7,12"

    def test_get_kept_narrative_for_stories(self, db):
        nid = db.save_narrative(1, "Kept story", story_ids=[3, 7])
        db.update_narrative(nid, status="kept")

        found = db.get_kept_narrative_for_stories(1, [3, 7])
        assert found is not None
        assert found["narrative"] == "Kept story"

        not_found = db.get_kept_narrative_for_stories(1, [99, 100])
        assert not_found is None

    def test_unkeep_narrative(self, db):
        nid = db.save_narrative(1, "Was kept", story_ids=[1])
        db.update_narrative(nid, status="kept")
        db.update_narrative(nid, status="draft")
        n = db.get_narrative(nid)
        assert n["status"] == "draft"


# ╔═══════════════════════════════════════════════════════════════╗
# ║              NARRATIVE LOG (rotation tracking)               ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestNarrativeRotation:
    """Narrative log tracks story usage for 7-day rotation."""

    def test_log_and_get_recent(self, db):
        # Need a story in the DB first
        conn = db._get_connection()
        conn.execute("INSERT INTO stories (tenant_id, transcript, source) VALUES (1, 'test', 'voice')")
        conn.commit()

        db.log_narrative_stories([1], tenant_id=1)
        recent = db.get_recently_narrated_story_ids(1, days=7)
        assert 1 in recent

    def test_empty_when_no_narratives(self, db):
        recent = db.get_recently_narrated_story_ids(1, days=7)
        assert len(recent) == 0


# ╔═══════════════════════════════════════════════════════════════╗
# ║              EDGE CASES & REGRESSIONS                        ║
# ╚═══════════════════════════════════════════════════════════════╝

class TestEdgeCases:
    """Edge cases for the new features."""

    def test_tell_me_about_still_works(self, parser):
        """'tell me about X' (bare, no 'story') should still extract query."""
        r = parser.parse("tell me about uncle bob")
        assert r["intent"] == "hear_stories"
        assert r["query"] == "uncle bob"

    def test_what_did_grandma_say(self, parser):
        """Existing phrase should still work."""
        r = parser.parse("what did grandma say")
        assert r["intent"] == "hear_stories"

    def test_story_about_with_trailing_punctuation(self, parser):
        """Query should strip trailing punctuation."""
        r = parser.parse("tell me a story about the lake?")
        assert r["intent"] == "hear_stories"
        assert r["query"] == "the lake"

    def test_say_a_prayer_vs_say_a_story(self, parser):
        """'say a prayer' = prayer, 'say a story' = hear_stories."""
        assert parser.parse("say a prayer")["intent"] == "prayer"
        assert parser.parse("say a story")["intent"] == "hear_stories"

    def test_any_stories_vs_any_stories_about(self, parser):
        """'any stories' = generic, 'any stories about X' = query."""
        r1 = parser.parse("any stories")
        assert r1["intent"] == "hear_stories"
        assert r1.get("query") is None

        r2 = parser.parse("any stories about the farm")
        assert r2["intent"] == "hear_stories"
        assert r2["query"] == "the farm"

    def test_prayer_request_different_tenants(self, db):
        """Prayer requests are tenant-scoped."""
        db.create_tenant("Other Family")
        db.add_prayer_request("Person A", tenant_id=1)
        db.add_prayer_request("Person B", tenant_id=2)

        t1 = db.get_prayer_requests(1)
        t2 = db.get_prayer_requests(2)
        assert len(t1) == 1
        assert len(t2) == 1
        assert t1[0]["name"] == "Person A"
        assert t2[0]["name"] == "Person B"

    def test_narrative_different_tenants(self, db):
        """Narratives are tenant-scoped."""
        db.create_tenant("Other Family")
        db.save_narrative(1, "Family 1 story", story_ids=[1])
        db.save_narrative(2, "Family 2 story", story_ids=[2])

        n1 = db.get_narratives(1)
        n2 = db.get_narratives(2)
        assert len(n1) == 1
        assert len(n2) == 1
