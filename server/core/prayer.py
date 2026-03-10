"""
Prayer service for Polly Connect.
Base prayers + AI-personalized prayers using family context.
"""

import json
import logging
import os
import random
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Time-of-day buckets
_MORNING_HOURS = range(5, 12)
_AFTERNOON_HOURS = range(12, 17)
_EVENING_HOURS = range(17, 21)
# Night = 21-5

# Prayer situations for variety when no theme is specified
_SITUATIONS = [
    "gratitude_family",      # Thank God for specific family members
    "gratitude_memories",    # Thank God for memories shared
    "protection_family",     # Pray for protection over family by name
    "children_grandchildren",# Pray for the kids/grandkids specifically
    "comfort_aging",         # Comfort for growing older
    "strength_daily",        # Strength for today
    "healing",               # Healing for body and mind
    "togetherness",          # Bringing family together
    "wisdom_guidance",       # Guidance and wisdom
    "peace_home",            # Peace in the home
    "joy_simple_things",     # Joy in simple blessings
    "legacy_purpose",        # Purpose and legacy
]


class PrayerService:
    def __init__(self, data_dir: str, db=None, followup_gen=None):
        self.prayers: List[dict] = []
        self.db = db
        self.followup_gen = followup_gen
        self._load_prayers(data_dir)

    def _load_prayers(self, data_dir: str):
        path = os.path.join(data_dir, "prayers.json")
        if not os.path.exists(path):
            logger.warning("prayers.json not found")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.prayers = json.load(f)
            logger.info(f"Loaded {len(self.prayers)} prayers")
        except Exception as e:
            logger.error(f"Error loading prayers: {e}")

    def get_prayer(self, theme: str = None, tenant_id: int = None) -> str:
        """Get a prayer — personalized with AI when possible, base prayer otherwise."""
        # Try AI personalized prayer ~60% of the time
        if (self.db and self.followup_gen and self.followup_gen.available
                and tenant_id and random.random() < 0.6):
            try:
                prayer = self._generate_personalized_prayer(theme, tenant_id)
                if prayer:
                    return prayer
            except Exception as e:
                logger.error(f"Personalized prayer error: {e}")

        # Fall back to base prayers
        return self._get_base_prayer(theme)

    def _get_base_prayer(self, theme: str = None) -> str:
        if not self.prayers:
            return "Let me pray for you in my heart. You are loved."
        if theme:
            matches = [p for p in self.prayers if p.get("theme") == theme]
            if matches:
                return random.choice(matches)["text"]
        return random.choice(self.prayers)["text"]

    def get_bedtime_prayer(self, tenant_id: int = None) -> str:
        return self.get_prayer(theme="bedtime", tenant_id=tenant_id)

    def _generate_personalized_prayer(self, theme: str, tenant_id: int) -> str:
        """Generate an AI prayer using family context, memories, and time of day."""
        now = datetime.now(ZoneInfo("America/Chicago"))
        hour = now.hour

        # Determine time context
        if hour in _MORNING_HOURS:
            time_context = "morning"
        elif hour in _AFTERNOON_HOURS:
            time_context = "afternoon"
        elif hour in _EVENING_HOURS:
            time_context = "evening"
        else:
            time_context = "nighttime"

        # Override theme based on time if no theme given
        if not theme and time_context == "nighttime":
            theme = "bedtime"

        # Gather close family only (parents, children, grandchildren, spouse, siblings)
        _close_relations = {
            "father", "mother", "son", "daughter", "husband", "wife", "spouse",
            "brother", "sister", "grandson", "granddaughter", "stepson", "stepdaughter",
            "father-in-law", "mother-in-law", "son-in-law", "daughter-in-law",
            "great-grandson", "great-granddaughter",
            "grandfather", "grandmother",
        }
        family_members = self.db.get_family_members(tenant_id=tenant_id)
        living_family = []
        deceased_family = []
        relationships = {}
        for fm in family_members:
            name = fm.get("name", "")
            rel = fm.get("relation_to_owner") or fm.get("relationship", "")
            if not name:
                continue
            # Only include close family in prayers
            if rel and rel.lower() not in _close_relations:
                continue
            if rel:
                relationships[name] = rel
            info = name
            if fm.get("spouse_name"):
                info += f" (married to {fm['spouse_name']})"
            if fm.get("bio"):
                info += f" — {fm['bio']}"
            if fm.get("deceased"):
                deceased_family.append(info)
            else:
                living_family.append(info)

        # Gather prayer requests
        prayer_requests = []
        try:
            prayer_requests = self.db.get_prayer_requests(tenant_id, active_only=True)
        except Exception:
            pass

        # Gather recent story snippets for context
        stories = self.db.get_stories(tenant_id=tenant_id, limit=10)
        story_snippets = []
        for s in stories[:5]:
            text = s.get("corrected_transcript") or s.get("transcript", "")
            if text and len(text) > 20:
                snippet = text[:150] + ("..." if len(text) > 150 else "")
                speaker = s.get("speaker_name", "")
                if speaker:
                    story_snippets.append(f"{speaker} shared: {snippet}")
                else:
                    story_snippets.append(snippet)

        # Pick a situation for variety
        if theme:
            situation = theme
        else:
            situation = random.choice(_SITUATIONS)

        # Build the prompt
        prompt = self._build_prayer_prompt(
            situation=situation,
            time_context=time_context,
            living_family=living_family,
            deceased_family=deceased_family,
            relationships=relationships,
            story_snippets=story_snippets,
            prayer_requests=prayer_requests,
            theme=theme,
        )

        response = self.followup_gen._client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.8,
        )

        prayer = response.choices[0].message.content.strip()
        # Collapse newlines into single spaces (TTS reads it as one spoken prayer)
        prayer = " ".join(prayer.split())

        # Hard cap at 100 words
        words = prayer.split()
        if len(words) > 100:
            truncated = " ".join(words[:100])
            # End at last sentence
            for end in ["Amen.", "amen.", ". Amen", "."]:
                idx = truncated.rfind(end)
                if idx > 30:
                    truncated = truncated[:idx + len(end)]
                    break
            if not truncated.rstrip().endswith("Amen."):
                truncated = truncated.rstrip().rstrip(".") + ". Amen."
            prayer = truncated

        # Ensure it ends with Amen
        if not prayer.rstrip().lower().endswith("amen."):
            prayer = prayer.rstrip().rstrip(".") + ". Amen."

        return prayer

    def _build_prayer_prompt(self, situation: str, time_context: str,
                              living_family: list, deceased_family: list,
                              relationships: dict, story_snippets: list,
                              prayer_requests: list = None,
                              theme: str = None) -> str:
        # Family context blocks
        family_block = ""
        if living_family:
            family_block = "LIVING FAMILY (close):\n" + "\n".join(
                f"- {f}" for f in living_family[:8]
            )
        if deceased_family:
            family_block += "\n\nDECEASED FAMILY (in heaven):\n" + "\n".join(
                f"- {f}" for f in deceased_family[:6]
            )

        # Prayer requests block
        request_block = ""
        if prayer_requests:
            lines = []
            for pr in prayer_requests[:5]:
                line = pr["name"]
                if pr.get("request"):
                    line += f": {pr['request']}"
                lines.append(f"- {line}")
            request_block = "PRAYER REQUESTS:\n" + "\n".join(lines)

        # Memory context block
        memory_block = ""
        if story_snippets:
            memory_block = "RECENT FAMILY MEMORIES:\n" + "\n".join(
                f"- {s}" for s in story_snippets[:4]
            )

        # Situation-specific guidance
        situation_guide = {
            "gratitude_family": "Thank God for specific family members BY NAME. Express gratitude for who they are and what they mean.",
            "gratitude_memories": "Thank God for the family memories and stories that have been shared. Reference the actual memories gently.",
            "protection_family": "Pray for God's protection over living family members BY NAME. Ask for safety, health, and guidance.",
            "children_grandchildren": "Pray specifically for the children and grandchildren in the family BY NAME. Ask for their growth, joy, and faith.",
            "comfort_aging": "Pray for comfort and peace in growing older. Thank God for the years and ask for grace in the days ahead.",
            "strength_daily": "Pray for strength to face today. Ask for energy, patience, and purpose.",
            "healing": "Pray for healing of body, mind, and spirit. Ask for God's restoring hand. If there are prayer requests for healing, mention them.",
            "togetherness": "Pray for the family to stay close and connected. Thank God for the bonds of love.",
            "wisdom_guidance": "Pray for wisdom and guidance in daily decisions. Ask for clarity and peace.",
            "peace_home": "Pray for peace in the home. Ask for harmony, laughter, and God's presence in every room.",
            "joy_simple_things": "Pray for joy in simple blessings — a warm meal, a phone call, a sunny day.",
            "legacy_purpose": "Pray about the legacy being left behind. Thank God for the stories and wisdom being passed down. Mention deceased family members fondly.",
            "bedtime": "A gentle bedtime prayer. Ask for peaceful rest, safety through the night, and God's presence while sleeping.",
            "family": "Pray for the whole close family by name. Lift each person up.",
            "hope": "Pray for hope and encouragement. Remind that God's plans are good.",
            "faith": "Pray for deeper faith and trust in God's plan.",
            "resilience": "Pray for strength and resilience in hard times.",
            "gratitude": "A prayer of thanksgiving for blessings big and small.",
        }

        guide = situation_guide.get(situation, situation_guide["gratitude_family"])

        prompt = f"""You are Polly, a faith-filled companion praying with an elderly person.
Write a SHORT, heartfelt prayer to God spoken aloud.

PRAYER DIRECTION: {guide}

TIME OF DAY: {time_context}

{family_block}

{request_block}

{memory_block}

Rules:
- Start with "Dear Lord," or "Heavenly Father," or "Dear God,"
- End with "Amen."
- MAXIMUM 4-5 sentences, 60-80 words. Keep it short enough to speak aloud.
- Use family member names naturally (don't list them all mechanically — pick 2-3)
- For DECEASED family: speak of them with love and gratitude ("thank You for the time we had with [name]", "we know [name] is with You now"). Never pray for their health or safety.
- For LIVING family: pray for protection, health, guidance, blessings
- If there are PRAYER REQUESTS, weave one or two in naturally
- If referencing memories, weave them in gently — don't quote them directly
- Warm, sincere, spoken tone — like praying out loud with a friend
- Christian prayer, non-denominational
- Do NOT be preachy or use complex theology
- This should feel personal and intimate, not generic"""

        return prompt
