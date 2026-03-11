"""
Prayer service for Polly Connect.
Base prayers + AI-personalized prayers organized by psychological need.
Categories rotate so the same prayer type doesn't repeat back-to-back.
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

# ── 15 prayer categories based on core human psychological needs ──
# Each has: key, label, guide (for GPT), uses_family (whether to include family context)
PRAYER_CATEGORIES = [
    {
        "key": "hope",
        "label": "Hope & Encouragement",
        "guide": "Pray for hope when life feels uncertain. Remind that brighter days are ahead and God has a plan. Encouraging and uplifting.",
        "uses_family": False,
    },
    {
        "key": "anxiety",
        "label": "Worry & Anxiety",
        "guide": "Pray for relief from worry, fear, and anxious thoughts. Ask God to calm the mind and replace fear with peace. Soothing and reassuring.",
        "uses_family": False,
    },
    {
        "key": "grief",
        "label": "Grief & Loss",
        "guide": "Pray for comfort after losing someone or missing a loved one. Acknowledge the pain, thank God for the time shared, and trust they are at peace.",
        "uses_family": True,  # uses deceased family
    },
    {
        "key": "loneliness",
        "label": "Loneliness & Isolation",
        "guide": "Pray for comfort when feeling alone or forgotten. Remind that God is always present and that loved ones care even from a distance.",
        "uses_family": True,
    },
    {
        "key": "gratitude",
        "label": "Gratitude & Blessings",
        "guide": "A prayer of pure thanksgiving — for small daily blessings, a warm meal, a phone call, the sunrise, good health, or a kind word.",
        "uses_family": False,
    },
    {
        "key": "strength",
        "label": "Strength & Tough Days",
        "guide": "Pray for strength to get through a hard day. Ask for energy, patience, and endurance. Acknowledge that some days are just hard.",
        "uses_family": False,
    },
    {
        "key": "healing",
        "label": "Healing & Health",
        "guide": "Pray for healing of body, mind, and spirit. Ask for God's restoring hand, for good doctors, and for patience in recovery.",
        "uses_family": True,  # uses prayer requests
    },
    {
        "key": "family",
        "label": "Family & Togetherness",
        "guide": "Pray for the family to stay close and connected. Thank God for the bonds of love. Mention 2-3 family members by name naturally.",
        "uses_family": True,
    },
    {
        "key": "peace",
        "label": "Peace & Calm",
        "guide": "Pray for inner peace — quiet the noise, still the heart, and rest in God's presence. A calming, meditative prayer.",
        "uses_family": False,
    },
    {
        "key": "faith",
        "label": "Faith & Trust",
        "guide": "Pray for deeper faith when doubt creeps in. Trust God's plan even when the road is unclear. Honest and vulnerable.",
        "uses_family": False,
    },
    {
        "key": "forgiveness",
        "label": "Forgiveness & Letting Go",
        "guide": "Pray for the ability to forgive others and release bitterness. Ask for a free heart and God's grace to let go of past hurts.",
        "uses_family": False,
    },
    {
        "key": "purpose",
        "label": "Purpose & Legacy",
        "guide": "Pray about the meaning of life, the legacy being left behind, and the purpose God still has. Thank God for the stories and wisdom passed down.",
        "uses_family": True,
    },
    {
        "key": "joy",
        "label": "Joy & Celebration",
        "guide": "A joyful prayer celebrating life's good moments — a birthday, a visit, a sunny day, a grandchild's smile. Upbeat and warm.",
        "uses_family": True,
    },
    {
        "key": "rest",
        "label": "Rest & Sleep",
        "guide": "A gentle bedtime prayer for peaceful rest. Let go of the day's burdens. Ask for safety through the night and sweet sleep.",
        "uses_family": False,
    },
    {
        "key": "guidance",
        "label": "Wisdom & Guidance",
        "guide": "Pray for wisdom in daily decisions — big or small. Ask for clarity, discernment, and the courage to follow God's leading.",
        "uses_family": False,
    },
]

# Map theme keywords → category keys
_THEME_TO_CATEGORY = {
    "bedtime": "rest", "hope": "hope", "faith": "faith",
    "resilience": "strength", "gratitude": "gratitude", "family": "family",
    "healing": "healing", "comfort_aging": "loneliness",
    "peace_home": "peace", "strength_daily": "strength",
    "children_grandchildren": "family", "gratitude_memories": "purpose",
    "protection_family": "family", "legacy_purpose": "purpose",
}

# Build lookup dict
_CATEGORY_MAP = {c["key"]: c for c in PRAYER_CATEGORIES}


class PrayerService:
    def __init__(self, data_dir: str, db=None, followup_gen=None):
        self.prayers: List[dict] = []
        self.db = db
        self.followup_gen = followup_gen
        self._recent_categories: dict = {}  # tenant_id → list of recent category keys
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

    def _pick_category(self, theme: str, tenant_id: int) -> dict:
        """Pick a prayer category, rotating to avoid repeats."""
        # If user asked for a specific theme, use it
        if theme:
            key = _THEME_TO_CATEGORY.get(theme, theme)
            if key in _CATEGORY_MAP:
                return _CATEGORY_MAP[key]

        # Get recently used categories for this tenant
        recent = self._recent_categories.get(tenant_id, [])

        # Filter out recent categories (last 5 used)
        available = [c for c in PRAYER_CATEGORIES if c["key"] not in recent[-5:]]
        if not available:
            available = PRAYER_CATEGORIES  # reset if all used

        # At nighttime, weight "rest" higher
        now = datetime.now(ZoneInfo("America/Chicago"))
        if now.hour >= 21 or now.hour < 5:
            rest_cats = [c for c in available if c["key"] == "rest"]
            if rest_cats and random.random() < 0.4:
                choice = rest_cats[0]
            else:
                choice = random.choice(available)
        else:
            choice = random.choice(available)

        # Track it
        if tenant_id not in self._recent_categories:
            self._recent_categories[tenant_id] = []
        self._recent_categories[tenant_id].append(choice["key"])
        # Keep only last 10
        self._recent_categories[tenant_id] = self._recent_categories[tenant_id][-10:]

        return choice

    def get_prayer(self, theme: str = None, tenant_id: int = None,
                    pray_for: str = None) -> str:
        """Get a prayer — personalized with AI when possible, base prayer otherwise."""
        # Always use AI if praying for a specific person
        use_ai = pray_for or random.random() < 0.65
        if self.db and self.followup_gen and self.followup_gen.available and tenant_id and use_ai:
            try:
                prayer = self._generate_personalized_prayer(theme, tenant_id, pray_for)
                if prayer:
                    return prayer
            except Exception as e:
                logger.error(f"Personalized prayer error: {e}")

        return self._get_base_prayer(theme)

    def _get_base_prayer(self, theme: str = None) -> str:
        if not self.prayers:
            return "Let me pray for you in my heart. You are loved."
        if theme:
            # Map theme to base prayer themes
            base_theme = _THEME_TO_CATEGORY.get(theme, theme)
            theme_map = {
                "rest": "bedtime", "strength": "resilience", "anxiety": "hope",
                "grief": "hope", "loneliness": "hope", "peace": "bedtime",
                "guidance": "faith", "forgiveness": "faith", "joy": "gratitude",
                "purpose": "gratitude", "family": "family",
            }
            base_key = theme_map.get(base_theme, base_theme)
            matches = [p for p in self.prayers if p.get("theme") == base_key]
            if matches:
                return random.choice(matches)["text"]
        return random.choice(self.prayers)["text"]

    def get_bedtime_prayer(self, tenant_id: int = None) -> str:
        return self.get_prayer(theme="bedtime", tenant_id=tenant_id)

    def _generate_personalized_prayer(self, theme: str, tenant_id: int,
                                       pray_for: str = None) -> str:
        """Generate an AI prayer based on a rotating psychological category."""
        now = datetime.now(ZoneInfo("America/Chicago"))
        hour = now.hour

        if hour in _MORNING_HOURS:
            time_context = "morning"
        elif hour in _AFTERNOON_HOURS:
            time_context = "afternoon"
        elif hour in _EVENING_HOURS:
            time_context = "evening"
        else:
            time_context = "nighttime"

        # Pick a category (rotating, avoids repeats)
        category = self._pick_category(theme, tenant_id)
        logger.info(f"Prayer category: {category['key']} ({category['label']})")

        # Gather family context if the category uses it
        living_family = []
        deceased_family = []
        prayer_requests = []
        memory_snippets = []
        pray_for_is_family = False

        _close_relations = {
            "father", "mother", "son", "daughter", "husband", "wife", "spouse",
            "brother", "sister", "grandson", "granddaughter", "stepson", "stepdaughter",
            "father-in-law", "mother-in-law", "son-in-law", "daughter-in-law",
            "great-grandson", "great-granddaughter",
            "grandfather", "grandmother",
        }

        if category["uses_family"] or pray_for:
            family_members = self.db.get_family_members(tenant_id=tenant_id)

            # Check if pray_for person is in the family tree
            if pray_for:
                pray_for_lower = pray_for.lower().strip()
                for fm in family_members:
                    if fm.get("name", "").lower().strip() == pray_for_lower:
                        pray_for_is_family = True
                        break

            # Only load family names if category needs them OR pray_for is a family member
            if category["uses_family"] or pray_for_is_family:
                for fm in family_members:
                    name = fm.get("name", "")
                    rel = fm.get("relation_to_owner") or fm.get("relationship", "")
                    if not name:
                        continue
                    if rel and rel.lower() not in _close_relations:
                        continue
                    info = name
                    if fm.get("spouse_name"):
                        info += f" (married to {fm['spouse_name']})"
                    if fm.get("deceased"):
                        deceased_family.append(info)
                    else:
                        living_family.append(info)

            # Prayer requests — for healing/family/grief, or when praying for someone specific
            if category["key"] in ("healing", "family", "grief") or pray_for:
                try:
                    prayer_requests = self.db.get_prayer_requests(tenant_id, active_only=True)
                    # If praying for a specific non-family person, only include their request
                    if pray_for and not pray_for_is_family:
                        prayer_requests = [pr for pr in prayer_requests
                                           if pr["name"].lower().strip() == pray_for.lower().strip()]
                except Exception:
                    pass

            # Story snippets — only for purpose/grief/joy
            if category["key"] in ("purpose", "grief", "joy"):
                stories = self.db.get_stories(tenant_id=tenant_id, limit=10)
                for s in stories[:3]:
                    text = s.get("corrected_transcript") or s.get("transcript", "")
                    if text and len(text) > 20:
                        snippet = text[:120] + ("..." if len(text) > 120 else "")
                        memory_snippets.append(snippet)

        # Build prompt — don't pass family context for non-family pray_for
        if pray_for and not pray_for_is_family:
            prompt = self._build_prompt(category, time_context, [], [],
                                         prayer_requests, [],
                                         pray_for=pray_for, pray_for_is_family=False)
        else:
            prompt = self._build_prompt(category, time_context, living_family,
                                         deceased_family, prayer_requests, memory_snippets,
                                         pray_for=pray_for, pray_for_is_family=pray_for_is_family)

        response = self.followup_gen._client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=180,
            temperature=0.85,
        )

        prayer = response.choices[0].message.content.strip()
        prayer = " ".join(prayer.split())  # collapse newlines

        # Hard cap at 80 words
        words = prayer.split()
        if len(words) > 80:
            truncated = " ".join(words[:80])
            for end in ["Amen.", "amen.", "."]:
                idx = truncated.rfind(end)
                if idx > 30:
                    truncated = truncated[:idx + len(end)]
                    break
            if not truncated.rstrip().endswith("Amen."):
                truncated = truncated.rstrip().rstrip(".") + ". Amen."
            prayer = truncated

        if not prayer.rstrip().lower().endswith("amen."):
            prayer = prayer.rstrip().rstrip(".") + ". Amen."

        # Auto-delete used prayer requests (queue behavior)
        if prayer_requests:
            used_requests = prayer_requests[:3]  # same ones included in prompt
            for pr in used_requests:
                try:
                    self.db.delete_prayer_request(pr["id"])
                except Exception:
                    pass
            if used_requests:
                logger.info(f"Prayer queue: auto-deleted {len(used_requests)} request(s)")

        return prayer

    def _build_prompt(self, category: dict, time_context: str,
                       living_family: list, deceased_family: list,
                       prayer_requests: list, memory_snippets: list,
                       pray_for: str = None, pray_for_is_family: bool = False) -> str:
        context_blocks = []

        if living_family:
            context_blocks.append("LIVING FAMILY:\n" + "\n".join(
                f"- {f}" for f in living_family[:6]))
        if deceased_family:
            context_blocks.append("DECEASED (in heaven):\n" + "\n".join(
                f"- {f}" for f in deceased_family[:4]))
        if prayer_requests:
            lines = []
            for pr in prayer_requests[:3]:
                line = pr["name"]
                if pr.get("request"):
                    line += f": {pr['request']}"
                lines.append(f"- {line}")
            context_blocks.append("PRAYER REQUESTS:\n" + "\n".join(lines))
        if memory_snippets:
            context_blocks.append("FAMILY MEMORIES:\n" + "\n".join(
                f"- {s}" for s in memory_snippets[:3]))

        context = "\n\n".join(context_blocks) if context_blocks else "(no family context needed for this prayer)"

        pray_for_line = ""
        if pray_for:
            if pray_for_is_family:
                pray_for_line = f"\nPRAY SPECIFICALLY FOR: {pray_for} (family member). Center this prayer on {pray_for}. If they match a prayer request, include that context.\n"
            else:
                pray_for_line = f"\nPRAY SPECIFICALLY FOR: {pray_for}. Center this prayer entirely on {pray_for}. Do NOT mention any family members — {pray_for} is not part of the family. Use rich prayer language: strength, courage, hope, wisdom, glory, grace, perseverance, peace, comfort, resilience. If a prayer request is provided for {pray_for}, weave it in.\n"

        return f"""You are Polly, praying aloud with an elderly person.

CATEGORY: {category['label']}
DIRECTION: {category['guide']}{pray_for_line}
TIME OF DAY: {time_context}

{context}

Rules:
- Start with "Dear Lord," or "Heavenly Father," or "Dear God,"
- End with "Amen."
- MAXIMUM 4-5 sentences, 60-80 words
- If family names are provided, use 1-2 naturally (not all of them)
- For DECEASED: speak with love and gratitude, never pray for their health
- For LIVING: pray for protection, health, blessings
- If prayer requests given, weave one in naturally
- Warm, sincere, spoken tone — like praying with a friend
- Non-denominational Christian prayer
- Do NOT be preachy — keep it personal and intimate
- IMPORTANT: Make this prayer UNIQUE to the category. Do not default to a generic family blessing."""
