"""
Vision service for Polly Connect.
Uses OpenAI GPT-4 Vision to identify items in photos.
"""

import base64
import json
import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)


class VisionService:
    """Identifies items in photos using OpenAI GPT-4 Vision."""

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.available = bool(self.api_key)
        if not self.available:
            logger.warning("OPENAI_API_KEY not set — vision service unavailable")

    def identify_items(self, image_bytes: bytes, default_location: str = "") -> List[str]:
        """
        Send a photo to GPT-4 Vision and get back a list of identified items.
        Returns a list of item name strings.
        """
        if not self.available:
            logger.error("Vision service called but OPENAI_API_KEY not set")
            return []

        import urllib.request
        import urllib.error

        # Encode image to base64
        b64_image = base64.b64encode(image_bytes).decode("utf-8")

        location_hint = ""
        if default_location:
            location_hint = f" The photo was taken at/near: {default_location}."

        payload = {
            "model": "gpt-4o",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You identify physical items/objects in photos. "
                        "Return ONLY a JSON array of item names. "
                        "Be specific: say 'claw hammer' not just 'hammer', "
                        "'Phillips screwdriver' not just 'screwdriver'. "
                        "Include brand names if visible. "
                        "Skip walls, floors, shelving units themselves — only list items ON/IN them. "
                        "If you can't identify items clearly, return fewer items rather than guessing."
                    )
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"List all the identifiable items/objects in this photo.{location_hint} Return only a JSON array of strings."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64_image}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 1000,
            "temperature": 0.2,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            content = result["choices"][0]["message"]["content"].strip()
            # Parse JSON array from response (handle markdown code blocks)
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            items = json.loads(content)
            if isinstance(items, list):
                logger.info(f"Vision identified {len(items)} items")
                return [str(item) for item in items]

        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            logger.error(f"OpenAI Vision API error {e.code}: {body[:200]}")
        except json.JSONDecodeError:
            logger.error(f"Failed to parse Vision response as JSON: {content[:200]}")
        except Exception as e:
            logger.error(f"Vision service error: {e}")

        return []

    def narrate_photo(self, image_bytes: bytes, caption: str = "",
                      date_taken: str = "", comments=None) -> Optional[dict]:
        """Look at a family photo (plus its caption and any comments people left)
        and tell its story for the legacy book.

        Returns a dict:
          {
            "narrative": "<warm 2-4 sentence story of the moment>",
            "quotes": [{"speaker": "Mom", "quote": "..."}],   # pull-quotes
            "bucket","life_phase","estimated_year","people","locations",
            "emotions","summary","story_value"
          }
        or None on failure (caller falls back).
        """
        if not self.available:
            return None
        import urllib.request, urllib.error

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        ctx = []
        if caption:
            ctx.append(f"Caption: {caption}")
        if date_taken:
            ctx.append(f"Date: {date_taken}")
        if comments:
            joined = "\n".join(f"- {c.get('name','Someone')}: {c.get('text','')}"
                               for c in comments if c.get("text"))
            if joined:
                ctx.append("What family members said about this photo:\n" + joined)
        context_block = "\n".join(ctx) if ctx else "(no caption provided)"

        system = (
            "You are a warm family biographer writing for a legacy book. Look at "
            "the photo and read what the family said about it. Return STRICT JSON "
            "(no markdown):\n{\n"
            '  "narrative": "<2-4 warm sentences telling the story of this moment '
            "for the book; describe what is happening and why it matters. Do NOT "
            'invent specific names not provided.>",\n'
            '  "quotes": [{"speaker":"<name>","quote":"<a short, heartfelt line '
            'worth quoting from the comments>"}],\n'
            '  "story_value": <0.0-1.0>,\n'
            '  "bucket": "<ordinary_world | call_to_adventure | crossing_threshold '
            '| trials_allies_enemies | transformation | return_with_knowledge>",\n'
            '  "life_phase": "<childhood | adolescence | young_adult | adult | '
            'midlife | elder | reflection | unknown>",\n'
            '  "estimated_year": <year from the date, or null>,\n'
            '  "people": ["names"], "locations": ["places"],\n'
            '  "emotions": ["dominant emotions"],\n'
            '  "summary": "<one sentence, max 120 chars>"\n}'
        )
        payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text", "text": context_block},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{b64}", "detail": "high"}},
                ]},
            ],
            "max_tokens": 900,
            "temperature": 0.5,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            content = result["choices"][0]["message"]["content"].strip()
            parsed = json.loads(content)
            if not isinstance(parsed.get("quotes"), list):
                parsed["quotes"] = []
            return parsed
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            logger.error(f"narrate_photo API error {e.code}: {body[:200]}")
        except Exception as e:
            logger.error(f"narrate_photo error: {e}")
        return None
