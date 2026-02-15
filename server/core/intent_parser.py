"""
Intent Parser for Polly Connect
"""

import re
from typing import Dict, Optional


class IntentParser:
    def __init__(self, use_spacy: bool = False):
        self.use_spacy = False  # Disabled for simplicity
        
        self.container_words = {
            "drawer", "bin", "box", "shelf", "cabinet", "toolbox", "container",
            "bucket", "tray", "rack", "pegboard", "wall", "corner", "workbench",
            "bench", "table", "floor", "hook", "hanger", "bag", "case"
        }
        
    def parse(self, text: str) -> Dict:
        text = text.strip()
        if not text:
            return {"intent": "unknown", "confidence": 0.0}
            
        text_lower = text.lower()
        
        if self._is_help(text_lower):
            return {"intent": "help", "confidence": 1.0}
            
        if self._is_list(text_lower):
            return {"intent": "list_all", "confidence": 1.0}
            
        delete_match = self._is_delete(text_lower)
        if delete_match:
            return {"intent": "delete", "item": delete_match, "confidence": 0.9}
            
        location_query = self._is_location_query(text_lower)
        if location_query:
            return {"intent": "retrieve_location", "location": location_query, "confidence": 0.9}
            
        item_query = self._is_item_query(text_lower)
        if item_query:
            return {"intent": "retrieve_item", "item": item_query, "confidence": 0.9}
            
        store_result = self._is_store(text_lower)
        if store_result:
            return {
                "intent": "store",
                "item": store_result["item"],
                "location": store_result["location"],
                "context": store_result.get("context"),
                "confidence": 0.85
            }
            
        return {"intent": "unknown", "confidence": 0.0}
        
    def _is_help(self, text: str) -> bool:
        patterns = [r"\bhelp\b", r"\bwhat can you do\b", r"\bhow do (i|you)\b"]
        return any(re.search(p, text) for p in patterns)
        
    def _is_list(self, text: str) -> bool:
        patterns = [
            r"\blist (all|everything)\b",
            r"\bshow (all|everything)\b",
            r"\bwhat do you (know|remember)\b"
        ]
        return any(re.search(p, text) for p in patterns)
        
    def _is_delete(self, text: str) -> Optional[str]:
        patterns = [
            r"(?:forget|remove|delete)(?: about)? (?:the |my )?(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return None
        
    def _is_location_query(self, text: str) -> Optional[str]:
        patterns = [
            r"what(?:'s| is| do i have) in (?:the |my )?(.+?)(?:\?|$)",
            r"show me (?:the |my )?(.+?)(?:\?|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                location = match.group(1).strip()
                if self._looks_like_location(location):
                    return location
        return None
        
    def _is_item_query(self, text: str) -> Optional[str]:
        patterns = [
            r"where(?:'s| is| are| did i put)(?: the| my)? (.+?)(?:\?|$)",
            r"(?:find|locate)(?: the| my)? (.+?)(?:\?|$)",
            r"(?:i need|looking for)(?: the| my| a)? (.+?)(?:\?|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                item = match.group(1).strip()
                item = re.sub(r'\s+(?:at|is|are|again)$', '', item)
                if item and not self._looks_like_location(item):
                    return item
        return None
        
    def _is_store(self, text_lower: str) -> Optional[Dict]:
        patterns = [
            r"(?:the |my )?(.+?) (?:is|are|goes?) (?:in|on|under|behind|inside|next to|near|by|at) (?:the |my )?(.+)",
            r"(?:i )?(?:put|placed|stored|keep|left) (?:the |my )?(.+?) (?:in|on|under|behind|inside|next to|near|by|at) (?:the |my )?(.+)",
            r"(?:the |my )?(.+?) (?:in|on|under|behind|at) (?:the |my )?(.+)",  # Without "is"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                item, location = match.group(1).strip(), match.group(2).strip()
                if item and location and not self._looks_like_question(item):
                    return {"item": item, "location": location, "context": None}
        return None
        
    def _looks_like_question(self, text: str) -> bool:
        question_words = ["where", "what", "which", "how", "when", "why", "who"]
        return any(text.startswith(w) for w in question_words)
        
    def _looks_like_location(self, text: str) -> bool:
        text_lower = text.lower()
        for word in self.container_words:
            if word in text_lower:
                return True
        if re.search(r'(red|blue|green|black|white|yellow)\s+\w+', text_lower):
            return True
        if re.search(r'(left|right|top|bottom|front|back)\s+\w+', text_lower):
            return True
        return False
