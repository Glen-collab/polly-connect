"""
Pronunciation guide for Polly Connect.
Replaces words with SSML <sub> tags so AWS Polly says names correctly.
"""

import re
from typing import List, Dict


def apply_pronunciations(text: str, pronunciations: List[Dict]) -> str:
    """Replace words in text with SSML substitution tags.

    If the text already has <speak> tags (e.g. jokes with <break>),
    insert substitutions inside. Otherwise wrap in <speak>.

    pronunciations: list of {"word": "Nawrott", "phonetic": "Nore-Rott"}
    """
    if not pronunciations or not text:
        return text

    # Build replacement map (case-insensitive match, preserve original case)
    replacements = {}
    for p in pronunciations:
        word = p["word"].strip()
        phonetic = p["phonetic"].strip()
        if word and phonetic:
            replacements[word.lower()] = (word, phonetic)

    if not replacements:
        return text

    # Check if already SSML
    is_ssml = "<speak>" in text

    # Strip <speak> wrapper if present so we can work on inner text
    inner = text
    if is_ssml:
        inner = re.sub(r'^<speak>\s*', '', inner)
        inner = re.sub(r'\s*</speak>$', '', inner)

    # Apply substitutions using word-boundary regex (case-insensitive)
    for key, (original_word, phonetic) in replacements.items():
        pattern = r'\b' + re.escape(key) + r'\b'
        # Use a function to preserve the matched case in the alias
        def make_sub(match, ph=phonetic):
            return f'<sub alias="{ph}">{match.group(0)}</sub>'
        inner = re.sub(pattern, make_sub, inner, flags=re.IGNORECASE)

    return f"<speak>{inner}</speak>"
