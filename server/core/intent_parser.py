"""
Intent Parser for Polly Connect
Ported from The Parrot - uses spaCy for NLP with rule-based pattern matching
"""

import re
from typing import Dict, Optional, Tuple, List

# Try to import spaCy, fall back to regex-only if not available
try:
    import spacy
    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False
    print("[IntentParser] spaCy not available, using regex-only mode")


class IntentParser:
    """
    Parse natural language commands into structured intents.
    
    Supported intents:
    - store: Store an item's location
    - retrieve_item: Find where an item is
    - retrieve_location: List items in a location
    - delete: Forget an item
    - list_all: List all stored items
    - help: Show usage help
    - unknown: Unrecognized command
    """
    
    def __init__(self, use_spacy: bool = True):
        self.use_spacy = use_spacy and SPACY_AVAILABLE
        self.nlp = None
        
        if self.use_spacy:
            try:
                self.nlp = spacy.load("en_core_web_sm")
                print("[IntentParser] Loaded spaCy model")
            except OSError:
                print("[IntentParser] spaCy model not found, using regex-only")
                self.use_spacy = False
                
        # Common location words for extraction
        self.location_indicators = {
            "in", "on", "under", "behind", "inside", "next to", "beside",
            "above", "below", "near", "by", "at", "within"
        }
        
        # Storage containers / locations
        self.container_words = {
            "drawer", "bin", "box", "shelf", "cabinet", "toolbox", "container",
            "bucket", "tray", "rack", "pegboard", "wall", "corner", "workbench",
            "bench", "table", "floor", "hook", "hanger", "bag", "case"
        }
        
    def parse(self, text: str) -> Dict:
        """
        Parse user input and return intent with extracted entities.
        
        Returns:
            {
                "intent": str,  # store, retrieve_item, retrieve_location, list_all, delete, help, unknown
                "item": Optional[str],
                "location": Optional[str],
                "context": Optional[str],
                "confidence": float
            }
        """
        text = text.strip()
        if not text:
            return {"intent": "unknown", "confidence": 0.0}
            
        text_lower = text.lower()
        
        # Check for help intent
        if self._is_help(text_lower):
            return {"intent": "help", "confidence": 1.0}
            
        # Check for list intent
        if self._is_list(text_lower):
            return {"intent": "list_all", "confidence": 1.0}
            
        # Check for delete intent
        delete_match = self._is_delete(text_lower)
        if delete_match:
            return {
                "intent": "delete",
                "item": delete_match,
                "confidence": 0.9
            }
            
        # Check for retrieve_location intent ("what's in the red bin?")
        location_query = self._is_location_query(text_lower)
        if location_query:
            return {
                "intent": "retrieve_location",
                "location": location_query,
                "confidence": 0.9
            }
            
        # Check for retrieve_item intent ("where is the wrench?")
        item_query = self._is_item_query(text_lower)
        if item_query:
            return {
                "intent": "retrieve_item",
                "item": item_query,
                "confidence": 0.9
            }
            
        # Check for store intent ("the wrench is in the drawer")
        store_result = self._is_store(text_lower, text)
        if store_result:
            return {
                "intent": "store",
                "item": store_result["item"],
                "location": store_result["location"],
                "context": store_result.get("context"),
                "confidence": store_result.get("confidence", 0.8)
            }
            
        # Unknown intent
        return {"intent": "unknown", "confidence": 0.0}
        
    def _is_help(self, text: str) -> bool:
        """Check if user is asking for help."""
        help_patterns = [
            r"\bhelp\b", r"\bwhat can you do\b", r"\bhow do (i|you)\b",
            r"\bcommands\b", r"\binstructions\b", r"\bexamples?\b"
        ]
        return any(re.search(p, text) for p in help_patterns)
        
    def _is_list(self, text: str) -> bool:
        """Check if user wants to list all items."""
        list_patterns = [
            r"\blist (all|everything)\b",
            r"\bshow (all|everything|me everything)\b",
            r"\bwhat('s| is| do you have) (all |stored|saved|everything)\b",
            r"\bwhat do you (know|remember)\b",
            r"\beverything you (know|remember)\b"
        ]
        return any(re.search(p, text) for p in list_patterns)
        
    def _is_delete(self, text: str) -> Optional[str]:
        """Check if user wants to delete an item. Returns item name or None."""
        delete_patterns = [
            r"(?:forget|remove|delete|clear|erase)(?: about)? (?:the |my )?(.+)",
            r"(?:i )?(?:got rid of|threw away|moved|lost) (?:the |my )?(.+)",
        ]
        for pattern in delete_patterns:
            match = re.search(pattern, text)
            if match:
                item = match.group(1).strip()
                # Clean up trailing words
                item = re.sub(r'\s+(please|now|already)$', '', item)
                return item
        return None
        
    def _is_location_query(self, text: str) -> Optional[str]:
        """Check if user is asking about a location. Returns location or None."""
        patterns = [
            r"what(?:'s| is| do i have) in (?:the |my )?(.+?)(?:\?|$)",
            r"what(?:'s| is) (?:stored |kept )?in (?:the |my )?(.+?)(?:\?|$)",
            r"show me (?:the |my )?(.+?)(?:\?|$)",
            r"(?:list|check) (?:the |my )?(.+?)(?:\?|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                location = match.group(1).strip()
                # Verify it looks like a location
                if self._looks_like_location(location):
                    return location
        return None
        
    def _is_item_query(self, text: str) -> Optional[str]:
        """Check if user is asking where an item is. Returns item name or None."""
        patterns = [
            r"where(?:'s| is| are| did i put)(?: the| my)? (.+?)(?:\?|$)",
            r"(?:find|locate)(?: the| my)? (.+?)(?:\?|$)",
            r"(?:do you know where)(?: the| my)? (.+?) (?:is|are)(?:\?|$)",
            r"(?:have you seen|seen)(?: the| my)? (.+?)(?:\?|$)",
            r"(?:i need|looking for|i'm looking for)(?: the| my| a)? (.+?)(?:\?|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                item = match.group(1).strip()
                # Clean up common trailing words
                item = re.sub(r'\s+(?:at|is|are|again)$', '', item)
                if item and not self._looks_like_location(item):
                    return item
        return None
        
    def _is_store(self, text_lower: str, text_original: str) -> Optional[Dict]:
        """
        Check if user is storing an item location.
        Returns dict with item, location, context or None.
        """
        # Pattern: "[item] is in/on/etc [location]"
        patterns = [
            # "the wrench is in the left drawer"
            r"(?:the |my )?(.+?) (?:is|are|goes?|go) (?:in|on|under|behind|inside|next to|beside|near|by|at) (?:the |my )?(.+)",
            # "put the wrench in the drawer" 
            r"(?:i )?(?:put|placed|stored|keep|left) (?:the |my )?(.+?) (?:in|on|under|behind|inside|next to|beside|near|by|at) (?:the |my )?(.+)",
            # "in the drawer is the wrench" (inverted)
            r"(?:in|on|under|behind|inside) (?:the |my )?(.+?) (?:is|are|there'?s?) (?:the |my |a |an )?(.+)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                groups = match.groups()
                
                # Handle inverted pattern
                if pattern.startswith(r"(?:in|on"):
                    location, item = groups[0], groups[1]
                else:
                    item, location = groups[0], groups[1]
                    
                # Clean up
                item = item.strip()
                location = location.strip()
                
                # Extract context (anything after common context indicators)
                context = None
                context_patterns = [
                    r",?\s*(?:behind|next to|beside|near|on top of|underneath|in front of) (?:the )?(.+)",
                    r",?\s*(?:in the|on the) (.+?) (?:section|area|part|side)",
                ]
                for cp in context_patterns:
                    context_match = re.search(cp, location)
                    if context_match:
                        context = context_match.group(0).strip(" ,")
                        location = location[:context_match.start()].strip()
                        break
                        
                if item and location:
                    return {
                        "item": item,
                        "location": location,
                        "context": context,
                        "confidence": 0.85
                    }
                    
        return None
        
    def _looks_like_location(self, text: str) -> bool:
        """Check if text looks like a location/container."""
        text_lower = text.lower()
        
        # Check for container words
        for word in self.container_words:
            if word in text_lower:
                return True
                
        # Check for color + container patterns
        if re.search(r'(red|blue|green|black|white|gray|grey|yellow|orange)\s+\w+', text_lower):
            return True
            
        # Check for position indicators
        if re.search(r'(left|right|top|bottom|middle|front|back|upper|lower)\s+\w+', text_lower):
            return True
            
        return False
        
    def extract_entities_spacy(self, text: str) -> Dict:
        """Use spaCy for entity extraction (when available)."""
        if not self.nlp:
            return {}
            
        doc = self.nlp(text)
        
        entities = {
            "nouns": [],
            "locations": [],
            "objects": []
        }
        
        for token in doc:
            # Collect nouns
            if token.pos_ in ("NOUN", "PROPN"):
                entities["nouns"].append(token.text)
                
        # Check for location entities
        for ent in doc.ents:
            if ent.label_ in ("LOC", "FAC", "GPE"):
                entities["locations"].append(ent.text)
                
        return entities


# Test the parser
if __name__ == "__main__":
    parser = IntentParser(use_spacy=False)
    
    test_cases = [
        # Store intents
        "the wrench is in the left drawer",
        "the wrench is in the left drawer behind the screwdrivers",
        "my hammer is on the pegboard",
        "put the drill in the red bin",
        "I left the screwdriver on the workbench",
        
        # Retrieve item intents
        "where is the wrench?",
        "where's my hammer",
        "where did I put the drill",
        "find the screwdriver",
        "I need the pliers",
        
        # Retrieve location intents
        "what's in the red bin?",
        "what is in the left drawer",
        "what do I have in the toolbox",
        "show me the pegboard",
        
        # Delete intents
        "forget the wrench",
        "forget about the hammer",
        "delete the drill",
        "I threw away the old screwdriver",
        
        # List intents
        "list everything",
        "show all",
        "what do you know",
        
        # Help intents
        "help",
        "what can you do",
        "how do I use this",
    ]
    
    print("Testing Intent Parser\n" + "=" * 50)
    for test in test_cases:
        result = parser.parse(test)
        print(f"\nInput: {test}")
        print(f"Result: {result}")
