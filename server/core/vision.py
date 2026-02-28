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
