"""
Tests for age-aware question system.
Verifies that different ages get appropriate question banks.
"""
import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from core.data_loader import DataLoader

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


@pytest.fixture
def loader():
    return DataLoader(DATA_DIR)


class TestQuestionBanksLoaded:
    """Verify all question banks load correctly."""

    def test_kids_bank_loaded(self, loader):
        assert len(loader._questions_kids) == 300

    def test_adolescent_bank_loaded(self, loader):
        assert len(loader._questions_adolescent) == 300

    def test_adult_bank_loaded(self, loader):
        assert len(loader._questions_adult) == 300

    def test_legacy_bank_loaded(self, loader):
        assert len(loader._all_questions) == 312

    def test_family_bank_loaded(self, loader):
        assert len(loader._all_family_questions) == 70


class TestAgeSelection:
    """Verify age-appropriate question selection."""

    def test_age_5_gets_kids_question(self, loader):
        q = loader.get_question(owner_age=5)
        assert q is not None
        assert q.get("age_group") == "kids"

    def test_age_10_gets_kids_question(self, loader):
        q = loader.get_question(owner_age=10)
        assert q is not None
        assert q.get("age_group") == "kids"

    def test_age_12_gets_kids_question(self, loader):
        q = loader.get_question(owner_age=12)
        assert q is not None
        assert q.get("age_group") == "kids"

    def test_age_13_gets_adolescent_question(self, loader):
        q = loader.get_question(owner_age=13)
        assert q is not None
        assert q.get("age_group") == "adolescent"

    def test_age_16_gets_adolescent_question(self, loader):
        q = loader.get_question(owner_age=16)
        assert q is not None
        assert q.get("age_group") == "adolescent"

    def test_age_22_gets_adolescent_question(self, loader):
        q = loader.get_question(owner_age=22)
        assert q is not None
        assert q.get("age_group") == "adolescent"

    def test_age_24_gets_adolescent_question(self, loader):
        q = loader.get_question(owner_age=24)
        assert q is not None
        assert q.get("age_group") == "adolescent"

    def test_age_25_gets_adult_question(self, loader):
        q = loader.get_question(owner_age=25)
        assert q is not None
        assert q.get("age_group") == "adult"

    def test_age_35_gets_adult_question(self, loader):
        q = loader.get_question(owner_age=35)
        assert q is not None
        assert q.get("age_group") == "adult"

    def test_age_47_gets_adult_question(self, loader):
        """Glen's age — should get adult questions."""
        q = loader.get_question(owner_age=47)
        assert q is not None
        assert q.get("age_group") == "adult"

    def test_age_50_gets_adult_question(self, loader):
        q = loader.get_question(owner_age=50)
        assert q is not None
        assert q.get("age_group") == "adult"

    def test_age_51_gets_legacy_question(self, loader):
        q = loader.get_question(owner_age=51)
        assert q is not None
        # Legacy questions don't have age_group set
        assert q.get("age_group") is None or q.get("age_group") == ""

    def test_age_75_gets_legacy_question(self, loader):
        q = loader.get_question(owner_age=75)
        assert q is not None

    def test_no_age_gets_legacy_question(self, loader):
        """No age specified — falls back to legacy bank."""
        q = loader.get_question(owner_age=None)
        assert q is not None

    def test_default_no_arg_gets_legacy(self, loader):
        """Calling with no argument at all works (backward compatible)."""
        q = loader.get_question()
        assert q is not None


class TestQuestionContent:
    """Verify question content is appropriate for each age group."""

    def test_kids_questions_are_fun(self, loader):
        """Kids questions should be imaginative and wonder-based."""
        themes = {q.get("theme") for q in loader._questions_kids}
        assert "imagination" in themes
        assert "animals" in themes
        assert "space" in themes

    def test_adolescent_questions_are_identity_focused(self, loader):
        """Adolescent questions should cover identity, relationships, mental health."""
        themes = {q.get("theme") for q in loader._questions_adolescent}
        assert "identity" in themes
        assert "mental_health" in themes
        assert "peer_pressure" in themes

    def test_adult_questions_are_reflective(self, loader):
        """Adult questions should be psychologist-style, open-ended."""
        themes = {q.get("theme") for q in loader._questions_adult}
        assert "career_and_purpose" in themes
        assert "parenting" in themes
        assert "loss_and_grief" in themes

    def test_kids_no_religious_leading(self, loader):
        """Kids questions should not lead into specific religions."""
        import re
        religious_terms = [r"\bgod\b", r"\bjesus\b", r"\bbible\b", r"\bchurch\b",
                          r"\bpray\b", r"\bsin\b", r"\bheaven\b", r"\bhell\b"]
        for q in loader._questions_kids:
            text = q["question"].lower()
            for pattern in religious_terms:
                assert not re.search(pattern, text), f"Kid question matches '{pattern}': {q['question']}"

    def test_adolescent_gender_neutral(self, loader):
        """Adolescent questions should be gender neutral."""
        import re
        gendered_patterns = [r"\bboyfriend\b", r"\bgirlfriend\b", r"\bhusband\b",
                             r"\bwife\b", r"\bhis\b", r"\bher\b"]
        for q in loader._questions_adolescent:
            text = q["question"].lower()
            for pattern in gendered_patterns:
                assert not re.search(pattern, text), f"Adolescent question matches '{pattern}': {q['question']}"


class TestQuestionDistribution:
    """Verify questions are well-distributed across themes."""

    def test_kids_50_themes(self, loader):
        themes = {q.get("theme") for q in loader._questions_kids}
        assert len(themes) >= 40  # at least 40 unique themes

    def test_adolescent_50_themes(self, loader):
        themes = {q.get("theme") for q in loader._questions_adolescent}
        assert len(themes) >= 40

    def test_adult_50_themes(self, loader):
        themes = {q.get("theme") for q in loader._questions_adult}
        assert len(themes) >= 40

    def test_all_questions_have_text(self, loader):
        """Every question across all banks should have non-empty text."""
        for bank_name, bank in [
            ("kids", loader._questions_kids),
            ("adolescent", loader._questions_adolescent),
            ("adult", loader._questions_adult),
        ]:
            for q in bank:
                assert q.get("question"), f"Empty question in {bank_name}: {q}"
                assert len(q["question"]) > 10, f"Question too short in {bank_name}: {q['question']}"

    def test_no_duplicate_ids(self, loader):
        """No duplicate question IDs across all banks."""
        all_ids = set()
        for bank in [loader._questions_kids, loader._questions_adolescent,
                     loader._questions_adult, loader._all_questions]:
            for q in bank:
                qid = q.get("id", "")
                if qid:
                    assert qid not in all_ids, f"Duplicate question ID: {qid}"
                    all_ids.add(qid)


class TestRandomness:
    """Verify questions are randomized."""

    def test_different_questions_returned(self, loader):
        """Multiple calls should return different questions (probabilistic)."""
        questions = set()
        for _ in range(20):
            q = loader.get_question(owner_age=30)
            questions.add(q["question"])
        # With 300 questions, 20 samples should give at least 10 unique
        assert len(questions) >= 10

    def test_age_boundary_consistency(self, loader):
        """Same age should always pull from same bank."""
        for _ in range(50):
            q = loader.get_question(owner_age=8)
            assert q.get("age_group") == "kids"
        for _ in range(50):
            q = loader.get_question(owner_age=18)
            assert q.get("age_group") == "adolescent"
        for _ in range(50):
            q = loader.get_question(owner_age=40)
            assert q.get("age_group") == "adult"
