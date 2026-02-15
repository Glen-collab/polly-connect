"""
Database module for Polly Connect
"""

import sqlite3
import re
from typing import Optional, List, Dict


class PollyDB:
    def __init__(self, db_path: str = "polly.db"):
        self.db_path = db_path
        self._conn = None
        if db_path == ":memory:":
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._init_db()
        
    def _get_connection(self):
        if self._conn:
            return self._conn
        return sqlite3.connect(self.db_path)
    
    def _init_db(self):
        conn = self._get_connection()
        try:
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_item_normalized ON items(item_normalized)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_location_normalized ON items(location_normalized)")
            conn.commit()
        finally:
            if not self._conn:
                conn.close()
            
    @staticmethod
    def _normalize(text: str) -> str:
        if not text:
            return ""
        text = text.lower().strip()
        text = re.sub(r'\b(the|a|an|my|that|this)\b', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def store_item(self, item: str, location: str, context: Optional[str] = None,
                   raw_input: Optional[str] = None) -> int:
        item_norm = self._normalize(item)
        location_norm = self._normalize(location)
        
        conn = self._get_connection()
        try:
            existing = conn.execute(
                "SELECT id FROM items WHERE item_normalized = ?", (item_norm,)
            ).fetchone()
            
            if existing:
                conn.execute("""
                    UPDATE items SET location = ?, location_normalized = ?, 
                    context = ?, raw_input = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (location, location_norm, context, raw_input, existing[0]))
                conn.commit()
                return existing[0]
            else:
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
            
    def find_item(self, item: str) -> List[Dict]:
        item_norm = self._normalize(item)
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            results = conn.execute("""
                SELECT id, item, location, context, created_at, updated_at
                FROM items WHERE item_normalized = ?
            """, (item_norm,)).fetchall()
            
            if not results:
                results = conn.execute("""
                    SELECT id, item, location, context, created_at, updated_at
                    FROM items WHERE item_normalized LIKE ?
                """, (f"%{item_norm}%",)).fetchall()
            
            return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()
            
    def find_by_location(self, location: str) -> List[Dict]:
        location_norm = self._normalize(location)
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            results = conn.execute("""
                SELECT id, item, location, context, created_at, updated_at
                FROM items WHERE location_normalized LIKE ?
            """, (f"%{location_norm}%",)).fetchall()
            return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()
            
    def list_all(self) -> List[Dict]:
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
        item_norm = self._normalize(item)
        conn = self._get_connection()
        try:
            cursor = conn.execute("DELETE FROM items WHERE item_normalized = ?", (item_norm,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if not self._conn:
                conn.close()
            
    def delete_by_id(self, item_id: int) -> bool:
        conn = self._get_connection()
        try:
            cursor = conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if not self._conn:
                conn.close()
            
    def search(self, query: str) -> List[Dict]:
        query_norm = self._normalize(query)
        if not query_norm:
            return []
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            results = conn.execute("""
                SELECT id, item, location, context, created_at, updated_at
                FROM items WHERE item LIKE ? OR location LIKE ? OR context LIKE ?
                LIMIT 20
            """, (f"%{query_norm}%",) * 3).fetchall()
            return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()
                
    def get_stats(self) -> Dict:
        conn = self._get_connection()
        try:
            total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            locations = conn.execute(
                "SELECT COUNT(DISTINCT location_normalized) FROM items"
            ).fetchone()[0]
            recent = conn.execute("""
                SELECT item, location FROM items ORDER BY updated_at DESC LIMIT 5
            """).fetchall()
            return {
                "total_items": total,
                "unique_locations": locations,
                "recent": [{"item": r[0], "location": r[1]} for r in recent]
            }
        finally:
            if not self._conn:
                conn.close()
