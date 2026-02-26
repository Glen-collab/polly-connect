"""
Memory verification service for Polly Connect.

Supports three verification states:
  - unverified (default — freshly captured)
  - verified (caretaker or family member confirmed)
  - disputed (someone flagged it as inaccurate)

Unverified memories can appear in narrative drafts but are flagged.
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class VerificationService:
    """Manages verification status for structured memories."""

    def __init__(self, db):
        self.db = db

    def verify_memory(self, memory_id: int, verifier_name: str,
                      verifier_relationship: str = None,
                      notes: str = None) -> bool:
        """Mark a memory as verified by a caretaker or family member."""
        return self.db.verify_memory(
            memory_id=memory_id,
            verifier_name=verifier_name,
            verifier_relationship=verifier_relationship,
            status="verified",
            notes=notes,
        )

    def dispute_memory(self, memory_id: int, verifier_name: str,
                       notes: str = None) -> bool:
        """Mark a memory as disputed (factual concern)."""
        return self.db.verify_memory(
            memory_id=memory_id,
            verifier_name=verifier_name,
            status="disputed",
            notes=notes,
        )

    def get_unverified(self, speaker: str = None, limit: int = 50) -> List[Dict]:
        """Get memories pending verification."""
        return self.db.get_memories(
            speaker=speaker,
            verification_status="unverified",
            limit=limit,
        )

    def get_verified(self, speaker: str = None, limit: int = 200) -> List[Dict]:
        """Get verified memories (for book building)."""
        return self.db.get_memories(
            speaker=speaker,
            verification_status="verified",
            limit=limit,
        )

    def get_verification_stats(self, speaker: str = None) -> Dict:
        """Get counts by verification status."""
        all_memories = self.db.get_memories(speaker=speaker, limit=9999)
        stats = {"unverified": 0, "verified": 0, "disputed": 0, "total": len(all_memories)}
        for mem in all_memories:
            status = mem.get("verification_status", "unverified")
            if status in stats:
                stats[status] += 1
        return stats
