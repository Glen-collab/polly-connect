"""
Database module for Polly Connect
Ported from The Parrot - SQLite-based storage for items and locations
"""

import sqlite3
from datetime import datetime
from typing import Optional, List, Dict
from pathlib import Path
import re


class PollyDB:
    """
    SQLite database for storing item locations.
    
    Features:
    - Normalized text matching
    - Full-text search (FTS5)
    - Fuzzy matching fallback
    """
    
    def __init__(self, db_path: str = "polly.db"):
        self.db_path = db_path
        self._conn = None
        # For in-memory databases, keep a persistent connection
        if db_path == ":memory:":
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._init_db()
        
    def _get_connection(self):
        """Get a database connection."""
        if self._conn:
            return self._conn
        return sqlite3.connect(self.db_path)
    
    def _init_db(self):
        """Initialize the database schema."""
        conn = self._get_connection()
        try:
            # Create main items table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item TEXT NOT NULL,
                    item_normalized TEXT NOT NULL,
                    location TEXT NOT NULL,
                    location_normalized TEXT NOT NULL,
                    context TEXT,
                    raw_input TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for faster lookups
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_item_normalized 
                ON items(item_normalized)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_location_normalized 
                ON items(location_normalized)
            """)
            
            conn.commit()
            
            # Try to create FTS table (may not be available in all SQLite builds)
            try:
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS items_fts 
                    USING fts5(item, location, context, content='items', content_rowid='id')
                """)
                
                # Triggers to keep FTS in sync
                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
                        INSERT INTO items_fts(rowid, item, location, context)
                        VALUES (new.id, new.item, new.location, new.context);
                    END
                """)
                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
                        INSERT INTO items_fts(items_fts, rowid, item, location, context)
                        VALUES ('delete', old.id, old.item, old.location, old.context);
                    END
                """)
                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN
                        INSERT INTO items_fts(items_fts, rowid, item, location, context)
                        VALUES ('delete', old.id, old.item, old.location, old.context);
                        INSERT INTO items_fts(rowid, item, location, context)
                        VALUES (new.id, new.item, new.location, new.context);
                    END
                """)
                conn.commit()
            except sqlite3.OperationalError as e:
                # FTS5 not available, will fall back to LIKE queries
                print(f"[DB] FTS5 not available, using LIKE fallback: {e}")
        finally:
            if not self._conn:
                conn.close()
            
    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize text for matching (lowercase, remove articles, etc.)"""
        if not text:
            return ""
        text = text.lower().strip()
        # Remove common articles and filler words
        text = re.sub(r'\b(the|a|an|my|that|this)\b', '', text)
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def store_item(self, item: str, location: str, context: Optional[str] = None,
                   raw_input: Optional[str] = None) -> int:
        """
        Store an item's location. Updates if item already exists.
        Returns the row ID.
        """
        item_norm = self._normalize(item)
        location_norm = self._normalize(location)
        
        conn = self._get_connection()
        try:
            # Check if item already exists
            existing = conn.execute(
                "SELECT id FROM items WHERE item_normalized = ?",
                (item_norm,)
            ).fetchone()
            
            if existing:
                # Update existing
                conn.execute("""
                    UPDATE items SET
                        location = ?,
                        location_normalized = ?,
                        context = ?,
                        raw_input = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (location, location_norm, context, raw_input, existing[0]))
                conn.commit()
                return existing[0]
            else:
                # Insert new
                cursor = conn.execute("""
                    INSERT INTO items (item, item_normalized, location, 
                                      location_normalized, context, raw_input)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (item, item_norm, location, location_norm, context, raw_input))
                conn.commit()
                return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()
            
    def find_item(self, item: str, fuzzy: bool = True) -> List[Dict]:
        """Find where an item is stored."""
        item_norm = self._normalize(item)
        
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            
            # Try exact match first
            results = conn.execute("""
                SELECT id, item, location, context, created_at, updated_at
                FROM items WHERE item_normalized = ?
            """, (item_norm,)).fetchall()
            
            if results:
                return [dict(r) for r in results]
            
            # Try partial match
            results = conn.execute("""
                SELECT id, item, location, context, created_at, updated_at
                FROM items WHERE item_normalized LIKE ?
            """, (f"%{item_norm}%",)).fetchall()
            
            if results:
                return [dict(r) for r in results]
            
            # Try FTS fuzzy match
            if fuzzy and item_norm:
                try:
                    results = conn.execute("""
                        SELECT i.id, i.item, i.location, i.context, 
                               i.created_at, i.updated_at
                        FROM items_fts fts
                        JOIN items i ON fts.rowid = i.id
                        WHERE items_fts MATCH ?
                        ORDER BY rank
                        LIMIT 5
                    """, (f"{item_norm}*",)).fetchall()
                    return [dict(r) for r in results]
                except sqlite3.OperationalError:
                    # FTS query failed, return empty
                    pass
                    
            return []
        finally:
            if not self._conn:
                conn.close()
            
    def find_by_location(self, location: str) -> List[Dict]:
        """Find all items in a location."""
        location_norm = self._normalize(location)
        
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            
            # Try exact match first
            results = conn.execute("""
                SELECT id, item, location, context, created_at, updated_at
                FROM items WHERE location_normalized = ?
            """, (location_norm,)).fetchall()
            
            if results:
                return [dict(r) for r in results]
            
            # Try partial match
            results = conn.execute("""
                SELECT id, item, location, context, created_at, updated_at
                FROM items WHERE location_normalized LIKE ?
            """, (f"%{location_norm}%",)).fetchall()
            
            return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()
            
    def list_all(self) -> List[Dict]:
        """List all stored items."""
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            results = conn.execute("""
                SELECT id, item, location, context, created_at, updated_at
                FROM items ORDER BY updated_at DESC
            """).fetchall()
            return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()
            
    def delete_item(self, item: str) -> bool:
        """Delete an item by name. Returns True if deleted."""
        item_norm = self._normalize(item)
        
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM items WHERE item_normalized = ?",
                (item_norm,)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if not self._conn:
                conn.close()
            
    def delete_by_id(self, item_id: int) -> bool:
        """Delete an item by ID. Returns True if deleted."""
        conn = self._get_connection()
        try:
            cursor = conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if not self._conn:
                conn.close()
            
    def search(self, query: str) -> List[Dict]:
        """Full-text search across items, locations, and context."""
        query_norm = self._normalize(query)
        
        if not query_norm:
            return []
        
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            
            try:
                results = conn.execute("""
                    SELECT i.id, i.item, i.location, i.context,
                           i.created_at, i.updated_at
                    FROM items_fts fts
                    JOIN items i ON fts.rowid = i.id
                    WHERE items_fts MATCH ?
                    ORDER BY rank
                    LIMIT 20
                """, (f"{query_norm}*",)).fetchall()
                return [dict(r) for r in results]
            except sqlite3.OperationalError:
                # Fall back to LIKE search
                results = conn.execute("""
                    SELECT id, item, location, context, created_at, updated_at
                    FROM items 
                    WHERE item LIKE ? OR location LIKE ? OR context LIKE ?
                    LIMIT 20
                """, (f"%{query_norm}%",) * 3).fetchall()
                return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()
                
    def get_stats(self) -> Dict:
        """Get database statistics."""
        conn = self._get_connection()
        try:
            total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            locations = conn.execute(
                "SELECT COUNT(DISTINCT location_normalized) FROM items"
            ).fetchone()[0]
            
            recent = conn.execute("""
                SELECT item, location FROM items 
                ORDER BY updated_at DESC LIMIT 5
            """).fetchall()
            
            return {
                "total_items": total,
                "unique_locations": locations,
                "recent": [{"item": r[0], "location": r[1]} for r in recent]
            }
        finally:
            if not self._conn:
                conn.close()


# Test the database
if __name__ == "__main__":
    db = PollyDB(":memory:")
    
    # Test storing
    db.store_item("wrench", "left drawer", "behind the screwdrivers")
    db.store_item("hammer", "pegboard", "on the right side")
    db.store_item("screwdriver set", "left drawer", "front section")
    db.store_item("drill", "red bin", "top shelf")
    db.store_item("drill bits", "red bin", "in the small container")
    
    print("All items:", db.list_all())
    print("\nFind wrench:", db.find_item("wrench"))
    print("\nFind drill:", db.find_item("drill"))
    print("\nIn left drawer:", db.find_by_location("left drawer"))
    print("\nIn red bin:", db.find_by_location("red bin"))
    print("\nSearch 'drill':", db.search("drill"))
    print("\nStats:", db.get_stats())
