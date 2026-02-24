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
            # ── Original items table ──
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

            # ── Device registration ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT UNIQUE NOT NULL,
                    api_key TEXT,
                    name TEXT,
                    user_id INTEGER REFERENCES user_profiles(id),
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP
                )
            """)

            # ── User profiles ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    familiar_name TEXT,
                    subscription_tier TEXT DEFAULT 'basic',
                    bible_topic_preference TEXT,
                    music_genre_preference TEXT,
                    memory_care_mode INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── Question sessions (Q&A tracking) ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS question_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES user_profiles(id),
                    question_id TEXT NOT NULL,
                    question_text TEXT NOT NULL,
                    answer_text TEXT,
                    audio_s3_key TEXT,
                    week INTEGER,
                    theme TEXT,
                    answered INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── Free-form stories ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS stories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES user_profiles(id),
                    transcript TEXT,
                    audio_s3_key TEXT,
                    speaker_name TEXT,
                    chapter TEXT,
                    source TEXT DEFAULT 'voice',
                    duration_seconds REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── Medication schedules ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS medications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES user_profiles(id),
                    name TEXT NOT NULL,
                    dosage TEXT,
                    times TEXT NOT NULL,
                    active_days TEXT DEFAULT '["mon","tue","wed","thu","fri","sat","sun"]',
                    active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── Medication compliance logs ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS medication_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    medication_id INTEGER REFERENCES medications(id),
                    status TEXT NOT NULL,
                    reminder_count INTEGER DEFAULT 0,
                    scheduled_time TEXT,
                    responded_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── Bible verses ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bible_verses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reference TEXT NOT NULL,
                    text TEXT NOT NULL,
                    reflection TEXT,
                    topic TEXT,
                    day_of_year INTEGER
                )
            """)

            # ── Joke history (prevent repeats) ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS joke_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES user_profiles(id),
                    joke_id TEXT NOT NULL,
                    told_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── Almanac weather ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS almanac_weather (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    year INTEGER NOT NULL,
                    week INTEGER NOT NULL,
                    region TEXT DEFAULT 'general',
                    forecast TEXT NOT NULL,
                    details TEXT
                )
            """)

            # ── Session tracking ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT,
                    user_id INTEGER REFERENCES user_profiles(id),
                    jokes_told INTEGER DEFAULT 0,
                    questions_asked INTEGER DEFAULT 0,
                    stories_recorded INTEGER DEFAULT 0,
                    duration_seconds REAL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP
                )
            """)

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

    # ── Items (memory storage) ──

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

    # ── Medications ──

    def add_medication(self, user_id: int, name: str, dosage: str, times: str,
                       active_days: str = None) -> int:
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                INSERT INTO medications (user_id, name, dosage, times, active_days)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, name, dosage, times,
                  active_days or '["mon","tue","wed","thu","fri","sat","sun"]'))
            conn.commit()
            return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()

    def get_medications(self, user_id: int = None) -> List[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            if user_id:
                results = conn.execute(
                    "SELECT * FROM medications WHERE user_id = ? AND active = 1", (user_id,)
                ).fetchall()
            else:
                results = conn.execute(
                    "SELECT * FROM medications WHERE active = 1"
                ).fetchall()
            return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()

    def log_medication(self, medication_id: int, status: str,
                       scheduled_time: str = None, reminder_count: int = 0) -> int:
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                INSERT INTO medication_logs (medication_id, status, scheduled_time, reminder_count)
                VALUES (?, ?, ?, ?)
            """, (medication_id, status, scheduled_time, reminder_count))
            conn.commit()
            return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()

    # ── Stories ──

    def save_story(self, transcript: str, audio_s3_key: str = None,
                   speaker_name: str = None, source: str = "voice",
                   duration_seconds: float = None, user_id: int = None) -> int:
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                INSERT INTO stories (user_id, transcript, audio_s3_key, speaker_name,
                                    source, duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, transcript, audio_s3_key, speaker_name, source, duration_seconds))
            conn.commit()
            return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()

    def get_stories(self, user_id: int = None, limit: int = 50) -> List[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            if user_id:
                results = conn.execute(
                    "SELECT * FROM stories WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit)
                ).fetchall()
            else:
                results = conn.execute(
                    "SELECT * FROM stories ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()

    # ── Question sessions ──

    def save_question_session(self, question_id: str, question_text: str,
                              answer_text: str = None, audio_s3_key: str = None,
                              week: int = None, theme: str = None,
                              user_id: int = None) -> int:
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                INSERT INTO question_sessions (user_id, question_id, question_text,
                    answer_text, audio_s3_key, week, theme, answered)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, question_id, question_text, answer_text, audio_s3_key,
                  week, theme, 1 if answer_text else 0))
            conn.commit()
            return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()

    # ── Bible verses ──

    def get_verse_by_day(self, day_of_year: int) -> Optional[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            result = conn.execute(
                "SELECT * FROM bible_verses WHERE day_of_year = ?", (day_of_year,)
            ).fetchone()
            return dict(result) if result else None
        finally:
            if not self._conn:
                conn.close()

    def get_verse_by_topic(self, topic: str) -> Optional[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            result = conn.execute(
                "SELECT * FROM bible_verses WHERE topic LIKE ? ORDER BY RANDOM() LIMIT 1",
                (f"%{topic}%",)
            ).fetchone()
            return dict(result) if result else None
        finally:
            if not self._conn:
                conn.close()

    # ── User profiles ──

    def get_or_create_user(self, name: str = "Default User") -> Dict:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            user = conn.execute("SELECT * FROM user_profiles LIMIT 1").fetchone()
            if user:
                return dict(user)
            cursor = conn.execute(
                "INSERT INTO user_profiles (name) VALUES (?)", (name,)
            )
            conn.commit()
            user = conn.execute(
                "SELECT * FROM user_profiles WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return dict(user)
        finally:
            if not self._conn:
                conn.close()
