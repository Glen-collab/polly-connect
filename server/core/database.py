"""
Database module for Polly Connect
"""

import hashlib
import json
import sqlite3
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional, List, Dict


class PollyDB:
    def __init__(self, db_path: str = "polly.db"):
        self.db_path = db_path
        self._conn = None
        if db_path == ":memory:":
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._init_db()
        self._run_migrations()

    def _get_connection(self):
        if self._conn:
            return self._conn
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        conn = self._get_connection()
        try:
            # Enable WAL mode for better concurrent access
            conn.execute("PRAGMA journal_mode=WAL")

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

            # ── Family members ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS family_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    name_normalized TEXT NOT NULL,
                    relationship TEXT,
                    primary_user_id INTEGER REFERENCES user_profiles(id),
                    visit_count INTEGER DEFAULT 1,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_family_name ON family_members(name_normalized)")

            # ── Story tags ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS story_tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    story_id INTEGER REFERENCES stories(id),
                    tag_type TEXT NOT NULL,
                    tag_value TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_story_tags ON story_tags(story_id)")

            # ── Structured memories (narrative-enriched) ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    story_id INTEGER REFERENCES stories(id),
                    speaker TEXT,
                    bucket TEXT DEFAULT 'ordinary_world',
                    life_phase TEXT DEFAULT 'unknown',
                    text_summary TEXT,
                    text TEXT,
                    people TEXT DEFAULT '[]',
                    locations TEXT DEFAULT '[]',
                    emotions TEXT DEFAULT '[]',
                    fingerprint TEXT,
                    verification_status TEXT DEFAULT 'unverified',
                    verified_by TEXT,
                    verified_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_speaker ON memories(speaker)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_bucket ON memories(bucket)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_verification ON memories(verification_status)")

            # ── Memory verifications (audit trail) ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_verifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id INTEGER REFERENCES memories(id),
                    verifier_name TEXT NOT NULL,
                    verifier_relationship TEXT,
                    status TEXT NOT NULL,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── Chapter drafts ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chapter_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chapter_number INTEGER,
                    title TEXT,
                    bucket TEXT,
                    life_phase TEXT,
                    memory_ids TEXT DEFAULT '[]',
                    content TEXT,
                    status TEXT DEFAULT 'draft',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

            # ── Photos ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES user_profiles(id),
                    filename TEXT NOT NULL,
                    original_name TEXT,
                    caption TEXT,
                    date_taken TEXT,
                    tags TEXT DEFAULT '[]',
                    story_id INTEGER REFERENCES stories(id),
                    uploaded_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── Family message board ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS family_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER,
                    from_name TEXT NOT NULL,
                    to_name TEXT,
                    message TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    read INTEGER DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_family_messages_tenant ON family_messages(tenant_id)")

            # ── Multi-tenant tables ──

            conn.execute("""
                CREATE TABLE IF NOT EXISTS tenants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    name TEXT NOT NULL,
                    tenant_id INTEGER REFERENCES tenants(id),
                    role TEXT DEFAULT 'caretaker',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_accounts_tenant ON accounts(tenant_id)")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS web_sessions (
                    id TEXT PRIMARY KEY,
                    account_id INTEGER REFERENCES accounts(id),
                    tenant_id INTEGER REFERENCES tenants(id),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_web_sessions_account ON web_sessions(account_id)")

            # ── Firmware versions (OTA updates) ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS firmware_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    variant TEXT NOT NULL,
                    version TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    file_size INTEGER,
                    file_hash TEXT,
                    release_notes TEXT,
                    is_active INTEGER DEFAULT 0,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def _run_migrations(self):
        """Add columns to existing tables (safe to run repeatedly)."""
        conn = self._get_connection()
        try:
            # Get existing columns for user_profiles
            cols = {row[1] for row in conn.execute("PRAGMA table_info(user_profiles)").fetchall()}
            migrations = {
                "owner_email": "ALTER TABLE user_profiles ADD COLUMN owner_email TEXT",
                "caretaker_name": "ALTER TABLE user_profiles ADD COLUMN caretaker_name TEXT",
                "caretaker_email": "ALTER TABLE user_profiles ADD COLUMN caretaker_email TEXT",
                "setup_complete": "ALTER TABLE user_profiles ADD COLUMN setup_complete INTEGER DEFAULT 0",
                "squawk_interval": "ALTER TABLE user_profiles ADD COLUMN squawk_interval INTEGER DEFAULT 10",
                "chatter_interval": "ALTER TABLE user_profiles ADD COLUMN chatter_interval INTEGER DEFAULT 45",
                "squawk_snoozed_until": "ALTER TABLE user_profiles ADD COLUMN squawk_snoozed_until TIMESTAMP",
                "quiet_hours_start": "ALTER TABLE user_profiles ADD COLUMN quiet_hours_start INTEGER DEFAULT 21",
                "quiet_hours_end": "ALTER TABLE user_profiles ADD COLUMN quiet_hours_end INTEGER DEFAULT 7",
            }
            for col, sql in migrations.items():
                if col not in cols:
                    conn.execute(sql)

            # Get existing columns for stories
            cols = {row[1] for row in conn.execute("PRAGMA table_info(stories)").fetchall()}
            migrations = {
                "verified": "ALTER TABLE stories ADD COLUMN verified INTEGER DEFAULT 0",
                "verified_by": "ALTER TABLE stories ADD COLUMN verified_by TEXT",
                "verified_at": "ALTER TABLE stories ADD COLUMN verified_at TIMESTAMP",
                "corrected_transcript": "ALTER TABLE stories ADD COLUMN corrected_transcript TEXT",
                "question_text": "ALTER TABLE stories ADD COLUMN question_text TEXT",
                "photo_id": "ALTER TABLE stories ADD COLUMN photo_id INTEGER REFERENCES photos(id)",
                "qr_in_book": "ALTER TABLE stories ADD COLUMN qr_in_book INTEGER DEFAULT 1",
            }
            for col, sql in migrations.items():
                if col not in cols:
                    conn.execute(sql)

            # ── Multi-tenant migrations: add tenant_id to all data tables ──
            tenant_tables = [
                "items", "stories", "question_sessions", "medications",
                "medication_logs", "joke_history", "family_members", "memories",
                "memory_verifications", "chapter_drafts", "sessions", "photos",
                "story_tags", "user_profiles", "devices", "family_messages",
            ]
            for table in tenant_tables:
                cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                if "tenant_id" not in cols:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN tenant_id INTEGER")

            # Add api_key_hash and firmware info to devices
            cols = {row[1] for row in conn.execute("PRAGMA table_info(devices)").fetchall()}
            if "api_key_hash" not in cols:
                conn.execute("ALTER TABLE devices ADD COLUMN api_key_hash TEXT")
            if "fw_version" not in cols:
                conn.execute("ALTER TABLE devices ADD COLUMN fw_version TEXT")
            if "fw_variant" not in cols:
                conn.execute("ALTER TABLE devices ADD COLUMN fw_variant TEXT")

            # Create default tenant #1 and backfill
            conn.execute("INSERT OR IGNORE INTO tenants (id, name) VALUES (1, 'Default')")
            for table in tenant_tables:
                conn.execute(f"UPDATE {table} SET tenant_id = 1 WHERE tenant_id IS NULL")

            # ── Family access code migrations ──
            # Add family_code columns to tenants
            cols = {row[1] for row in conn.execute("PRAGMA table_info(tenants)").fetchall()}
            if "family_code" not in cols:
                conn.execute("ALTER TABLE tenants ADD COLUMN family_code TEXT")
            if "family_code_created_at" not in cols:
                conn.execute("ALTER TABLE tenants ADD COLUMN family_code_created_at TIMESTAMP")

            # ── Items prep column ──
            cols = {row[1] for row in conn.execute("PRAGMA table_info(items)").fetchall()}
            if "prep" not in cols:
                conn.execute("ALTER TABLE items ADD COLUMN prep TEXT DEFAULT 'on'")

            # ── Family tree migrations ──
            cols = {row[1] for row in conn.execute("PRAGMA table_info(family_members)").fetchall()}
            fm_migrations = {
                "parent_member_id": "ALTER TABLE family_members ADD COLUMN parent_member_id INTEGER REFERENCES family_members(id)",
                "relation_to_owner": "ALTER TABLE family_members ADD COLUMN relation_to_owner TEXT",
                "generation": "ALTER TABLE family_members ADD COLUMN generation INTEGER DEFAULT 0",
            }
            for col, sql in fm_migrations.items():
                if col not in cols:
                    conn.execute(sql)

            # Add family_name and role columns to web_sessions
            cols = {row[1] for row in conn.execute("PRAGMA table_info(web_sessions)").fetchall()}
            if "family_name" not in cols:
                conn.execute("ALTER TABLE web_sessions ADD COLUMN family_name TEXT")
            if "role" not in cols:
                conn.execute("ALTER TABLE web_sessions ADD COLUMN role TEXT")

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

    # ── Tenant management ──

    def create_tenant(self, name: str) -> int:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "INSERT INTO tenants (name) VALUES (?)", (name,)
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()

    def get_tenant(self, tenant_id: int) -> Optional[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            result = conn.execute(
                "SELECT * FROM tenants WHERE id = ?", (tenant_id,)
            ).fetchone()
            return dict(result) if result else None
        finally:
            if not self._conn:
                conn.close()

    # ── Account management ──

    def create_account(self, email: str, password_hash: str, name: str,
                       tenant_id: int, role: str = "caretaker") -> int:
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                INSERT INTO accounts (email, password_hash, name, tenant_id, role)
                VALUES (?, ?, ?, ?, ?)
            """, (email, password_hash, name, tenant_id, role))
            conn.commit()
            return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()

    def get_account_by_email(self, email: str) -> Optional[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            result = conn.execute(
                "SELECT * FROM accounts WHERE email = ?", (email,)
            ).fetchone()
            return dict(result) if result else None
        finally:
            if not self._conn:
                conn.close()

    def get_account_by_id(self, account_id: int) -> Optional[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            result = conn.execute(
                "SELECT * FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
            return dict(result) if result else None
        finally:
            if not self._conn:
                conn.close()

    def update_account_login(self, account_id: int):
        conn = self._get_connection()
        try:
            conn.execute(
                "UPDATE accounts SET last_login = CURRENT_TIMESTAMP WHERE id = ?",
                (account_id,)
            )
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def has_accounts(self) -> bool:
        conn = self._get_connection()
        try:
            count = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
            return count > 0
        finally:
            if not self._conn:
                conn.close()

    # ── Web session management ──

    def create_web_session(self, account_id: int, tenant_id: int,
                           duration_hours: int = 72) -> str:
        session_id = secrets.token_urlsafe(32)
        expires_at = (datetime.utcnow() + timedelta(hours=duration_hours)).isoformat()
        conn = self._get_connection()
        try:
            conn.execute("""
                INSERT INTO web_sessions (id, account_id, tenant_id, expires_at)
                VALUES (?, ?, ?, ?)
            """, (session_id, account_id, tenant_id, expires_at))
            conn.commit()
            return session_id
        finally:
            if not self._conn:
                conn.close()

    def get_web_session(self, session_id: str) -> Optional[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            result = conn.execute("""
                SELECT ws.*, a.name as account_name, a.email as account_email,
                       a.role as account_role, ws.role as session_role, ws.family_name
                FROM web_sessions ws
                LEFT JOIN accounts a ON ws.account_id = a.id
                WHERE ws.id = ? AND ws.expires_at > datetime('now')
            """, (session_id,)).fetchone()
            return dict(result) if result else None
        finally:
            if not self._conn:
                conn.close()

    def touch_web_session(self, session_id: str):
        conn = self._get_connection()
        try:
            conn.execute(
                "UPDATE web_sessions SET last_active = CURRENT_TIMESTAMP WHERE id = ?",
                (session_id,)
            )
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def delete_web_session(self, session_id: str):
        conn = self._get_connection()
        try:
            conn.execute("DELETE FROM web_sessions WHERE id = ?", (session_id,))
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def cleanup_expired_sessions(self):
        conn = self._get_connection()
        try:
            conn.execute("DELETE FROM web_sessions WHERE expires_at <= datetime('now')")
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    # ── Family access code ──

    def generate_family_code(self, tenant_id: int) -> str:
        import random
        code = f"{random.randint(0, 999999):06d}"
        conn = self._get_connection()
        try:
            conn.execute(
                "UPDATE tenants SET family_code = ?, family_code_created_at = CURRENT_TIMESTAMP WHERE id = ?",
                (code, tenant_id)
            )
            conn.commit()
            return code
        finally:
            if not self._conn:
                conn.close()

    def revoke_family_code(self, tenant_id: int):
        conn = self._get_connection()
        try:
            conn.execute(
                "UPDATE tenants SET family_code = NULL, family_code_created_at = NULL WHERE id = ?",
                (tenant_id,)
            )
            # Kill all active family sessions for this tenant
            conn.execute(
                "DELETE FROM web_sessions WHERE tenant_id = ? AND role = 'family'",
                (tenant_id,)
            )
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def validate_family_code(self, code: str) -> Optional[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            result = conn.execute(
                "SELECT * FROM tenants WHERE family_code = ?", (code,)
            ).fetchone()
            return dict(result) if result else None
        finally:
            if not self._conn:
                conn.close()

    def create_family_session(self, tenant_id: int, family_name: str,
                              duration_hours: int = 72) -> str:
        session_id = secrets.token_urlsafe(32)
        expires_at = (datetime.utcnow() + timedelta(hours=duration_hours)).isoformat()
        conn = self._get_connection()
        try:
            conn.execute("""
                INSERT INTO web_sessions (id, account_id, tenant_id, expires_at, family_name, role)
                VALUES (?, NULL, ?, ?, ?, 'family')
            """, (session_id, tenant_id, expires_at, family_name))
            conn.commit()
            return session_id
        finally:
            if not self._conn:
                conn.close()

    # ── Device management (per-tenant) ──

    def register_device(self, device_id: str, tenant_id: int, name: str = None,
                        api_key: str = None) -> Dict:
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest() if api_key else None
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                "SELECT * FROM devices WHERE device_id = ?", (device_id,)
            ).fetchone()
            if existing:
                conn.execute("""
                    UPDATE devices SET tenant_id = ?, name = ?, api_key_hash = ?,
                    last_seen = CURRENT_TIMESTAMP WHERE device_id = ?
                """, (tenant_id, name or existing["name"], api_key_hash or existing["api_key_hash"],
                      device_id))
            else:
                conn.execute("""
                    INSERT INTO devices (device_id, tenant_id, name, api_key_hash)
                    VALUES (?, ?, ?, ?)
                """, (device_id, tenant_id, name, api_key_hash))
            conn.commit()
            result = conn.execute(
                "SELECT * FROM devices WHERE device_id = ?", (device_id,)
            ).fetchone()
            return dict(result)
        finally:
            if not self._conn:
                conn.close()

    def get_device_by_api_key_hash(self, api_key_hash: str) -> Optional[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            result = conn.execute(
                "SELECT * FROM devices WHERE api_key_hash = ?", (api_key_hash,)
            ).fetchone()
            return dict(result) if result else None
        finally:
            if not self._conn:
                conn.close()

    def get_devices_by_tenant(self, tenant_id: int) -> List[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            results = conn.execute(
                "SELECT * FROM devices WHERE tenant_id = ? ORDER BY registered_at DESC",
                (tenant_id,)
            ).fetchall()
            return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()

    def update_device_last_seen(self, device_id: str):
        conn = self._get_connection()
        try:
            conn.execute(
                "UPDATE devices SET last_seen = CURRENT_TIMESTAMP WHERE device_id = ?",
                (device_id,)
            )
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def delete_device(self, device_id: str, tenant_id: int) -> bool:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM devices WHERE device_id = ? AND tenant_id = ?",
                (device_id, tenant_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if not self._conn:
                conn.close()

    # ── Items (memory storage) ──

    def store_item(self, item: str, location: str, context: Optional[str] = None,
                   raw_input: Optional[str] = None, tenant_id: int = None,
                   prep: str = "on") -> int:
        item_norm = self._normalize(item)
        location_norm = self._normalize(location)

        conn = self._get_connection()
        try:
            if tenant_id:
                existing = conn.execute(
                    "SELECT id FROM items WHERE item_normalized = ? AND tenant_id = ?",
                    (item_norm, tenant_id)
                ).fetchone()
            else:
                existing = conn.execute(
                    "SELECT id FROM items WHERE item_normalized = ?", (item_norm,)
                ).fetchone()

            if existing:
                conn.execute("""
                    UPDATE items SET location = ?, location_normalized = ?,
                    context = ?, raw_input = ?, prep = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (location, location_norm, context, raw_input, prep, existing[0]))
                conn.commit()
                return existing[0]
            else:
                cursor = conn.execute("""
                    INSERT INTO items (item, item_normalized, location,
                                      location_normalized, context, raw_input, prep, tenant_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (item, item_norm, location, location_norm, context, raw_input, prep, tenant_id))
                conn.commit()
                return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()

    def find_item(self, item: str, tenant_id: int = None) -> List[Dict]:
        item_norm = self._normalize(item)
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            t_clause = " AND tenant_id = ?" if tenant_id else ""
            t_params = (tenant_id,) if tenant_id else ()

            results = conn.execute(
                f"SELECT id, item, location, context, prep, created_at, updated_at FROM items WHERE item_normalized = ?{t_clause}",
                (item_norm,) + t_params
            ).fetchall()

            if not results:
                results = conn.execute(
                    f"SELECT id, item, location, context, prep, created_at, updated_at FROM items WHERE item_normalized LIKE ?{t_clause}",
                    (f"%{item_norm}%",) + t_params
                ).fetchall()

            return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()

    def find_by_location(self, location: str, tenant_id: int = None) -> List[Dict]:
        location_norm = self._normalize(location)
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            t_clause = " AND tenant_id = ?" if tenant_id else ""
            t_params = (tenant_id,) if tenant_id else ()
            results = conn.execute(
                f"SELECT id, item, location, context, created_at, updated_at FROM items WHERE location_normalized LIKE ?{t_clause}",
                (f"%{location_norm}%",) + t_params
            ).fetchall()
            return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()

    def list_all(self, tenant_id: int = None) -> List[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            if tenant_id:
                results = conn.execute(
                    "SELECT id, item, location, context, created_at, updated_at FROM items WHERE tenant_id = ? ORDER BY updated_at DESC",
                    (tenant_id,)
                ).fetchall()
            else:
                results = conn.execute(
                    "SELECT id, item, location, context, created_at, updated_at FROM items ORDER BY updated_at DESC"
                ).fetchall()
            return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()

    def delete_item(self, item: str, tenant_id: int = None) -> bool:
        item_norm = self._normalize(item)
        conn = self._get_connection()
        try:
            if tenant_id:
                cursor = conn.execute(
                    "DELETE FROM items WHERE item_normalized = ? AND tenant_id = ?",
                    (item_norm, tenant_id)
                )
            else:
                cursor = conn.execute(
                    "DELETE FROM items WHERE item_normalized = ?", (item_norm,)
                )
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

    def search(self, query: str, tenant_id: int = None) -> List[Dict]:
        query_norm = self._normalize(query)
        if not query_norm:
            return []
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            t_clause = " AND tenant_id = ?" if tenant_id else ""
            t_params = (tenant_id,) if tenant_id else ()
            results = conn.execute(
                f"SELECT id, item, location, context, created_at, updated_at FROM items WHERE (item LIKE ? OR location LIKE ? OR context LIKE ?){t_clause} LIMIT 20",
                (f"%{query_norm}%",) * 3 + t_params
            ).fetchall()
            return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()

    def get_stats(self, tenant_id: int = None) -> Dict:
        conn = self._get_connection()
        try:
            t_clause = " WHERE tenant_id = ?" if tenant_id else ""
            t_params = (tenant_id,) if tenant_id else ()

            total = conn.execute(f"SELECT COUNT(*) FROM items{t_clause}", t_params).fetchone()[0]
            locations = conn.execute(
                f"SELECT COUNT(DISTINCT location_normalized) FROM items{t_clause}", t_params
            ).fetchone()[0]
            recent = conn.execute(
                f"SELECT item, location FROM items{t_clause} ORDER BY updated_at DESC LIMIT 5", t_params
            ).fetchall()
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
                       active_days: str = None, tenant_id: int = None) -> int:
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                INSERT INTO medications (user_id, name, dosage, times, active_days, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, name, dosage, times,
                  active_days or '["mon","tue","wed","thu","fri","sat","sun"]', tenant_id))
            conn.commit()
            return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()

    def get_medications(self, user_id: int = None, tenant_id: int = None) -> List[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM medications WHERE active = 1"
            params = []
            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)
            if tenant_id:
                query += " AND tenant_id = ?"
                params.append(tenant_id)
            results = conn.execute(query, params).fetchall()
            return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()

    def get_medication_by_id(self, medication_id: int, tenant_id: int = None) -> Optional[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM medications WHERE id = ?"
            params = [medication_id]
            if tenant_id:
                query += " AND tenant_id = ?"
                params.append(tenant_id)
            row = conn.execute(query, params).fetchone()
            return dict(row) if row else None
        finally:
            if not self._conn:
                conn.close()

    def update_medication(self, medication_id: int, name: str, dosage: str,
                          times: str, active_days: str = None,
                          tenant_id: int = None):
        conn = self._get_connection()
        try:
            query = "UPDATE medications SET name = ?, dosage = ?, times = ?"
            params = [name, dosage, times]
            if active_days is not None:
                query += ", active_days = ?"
                params.append(active_days)
            query += " WHERE id = ?"
            params.append(medication_id)
            if tenant_id:
                query += " AND tenant_id = ?"
                params.append(tenant_id)
            conn.execute(query, params)
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def delete_medication(self, medication_id: int, tenant_id: int = None):
        conn = self._get_connection()
        try:
            query = "DELETE FROM medications WHERE id = ?"
            params = [medication_id]
            if tenant_id:
                query += " AND tenant_id = ?"
                params.append(tenant_id)
            conn.execute(query, params)
            conn.commit()
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
                   duration_seconds: float = None, user_id: int = None,
                   tenant_id: int = None, question_text: str = None,
                   photo_id: int = None) -> int:
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                INSERT INTO stories (user_id, transcript, audio_s3_key, speaker_name,
                                    source, duration_seconds, tenant_id, question_text, photo_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, transcript, audio_s3_key, speaker_name, source,
                  duration_seconds, tenant_id, question_text, photo_id))
            conn.commit()
            return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()

    def get_stories(self, user_id: int = None, limit: int = 50,
                    tenant_id: int = None) -> List[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM stories WHERE 1=1"
            params = []
            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)
            if tenant_id:
                query += " AND tenant_id = ?"
                params.append(tenant_id)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            results = conn.execute(query, params).fetchall()
            rows = [dict(r) for r in results]
            # Convert UTC timestamps to local timezone for display
            try:
                from zoneinfo import ZoneInfo
                from datetime import datetime
                tz = ZoneInfo("America/Chicago")
                for row in rows:
                    if row.get("created_at"):
                        try:
                            dt = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
                            dt_utc = dt.replace(tzinfo=ZoneInfo("UTC"))
                            dt_local = dt_utc.astimezone(tz)
                            row["created_at"] = dt_local.strftime("%Y-%m-%d %I:%M %p")
                        except (ValueError, TypeError):
                            pass
            except ImportError:
                pass
            return rows
        finally:
            if not self._conn:
                conn.close()

    # ── Question sessions ──

    def save_question_session(self, question_id: str, question_text: str,
                              answer_text: str = None, audio_s3_key: str = None,
                              week: int = None, theme: str = None,
                              user_id: int = None, tenant_id: int = None) -> int:
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                INSERT INTO question_sessions (user_id, question_id, question_text,
                    answer_text, audio_s3_key, week, theme, answered, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, question_id, question_text, answer_text, audio_s3_key,
                  week, theme, 1 if answer_text else 0, tenant_id))
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
            # Search by topic first, then fall back to reference (e.g., "Psalm", "Proverbs")
            result = conn.execute(
                "SELECT * FROM bible_verses WHERE topic LIKE ? ORDER BY RANDOM() LIMIT 1",
                (f"%{topic}%",)
            ).fetchone()
            if not result:
                result = conn.execute(
                    "SELECT * FROM bible_verses WHERE reference LIKE ? ORDER BY RANDOM() LIMIT 1",
                    (f"%{topic}%",)
                ).fetchone()
            return dict(result) if result else None
        finally:
            if not self._conn:
                conn.close()

    # ── Family members ──

    def add_family_member(self, name: str, relationship: str = None,
                          primary_user_id: int = None,
                          tenant_id: int = None) -> int:
        name_norm = self._normalize(name)
        conn = self._get_connection()
        try:
            t_clause = " AND tenant_id = ?" if tenant_id else ""
            t_params = (tenant_id,) if tenant_id else ()

            existing = conn.execute(
                f"SELECT id FROM family_members WHERE name_normalized = ?{t_clause}",
                (name_norm,) + t_params
            ).fetchone()
            if existing:
                conn.execute("""
                    UPDATE family_members SET visit_count = visit_count + 1,
                    last_seen = CURRENT_TIMESTAMP WHERE id = ?
                """, (existing[0],))
                if relationship:
                    conn.execute(
                        "UPDATE family_members SET relationship = ? WHERE id = ?",
                        (relationship, existing[0])
                    )
                conn.commit()
                return existing[0]
            cursor = conn.execute("""
                INSERT INTO family_members (name, name_normalized, relationship,
                                           primary_user_id, tenant_id)
                VALUES (?, ?, ?, ?, ?)
            """, (name, name_norm, relationship, primary_user_id, tenant_id))
            conn.commit()
            return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()

    def find_family_member(self, name: str, tenant_id: int = None) -> Optional[Dict]:
        name_norm = self._normalize(name)
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            t_clause = " AND tenant_id = ?" if tenant_id else ""
            t_params = (tenant_id,) if tenant_id else ()

            result = conn.execute(
                f"SELECT * FROM family_members WHERE name_normalized = ?{t_clause}",
                (name_norm,) + t_params
            ).fetchone()
            if not result:
                result = conn.execute(
                    f"SELECT * FROM family_members WHERE name_normalized LIKE ?{t_clause}",
                    (f"%{name_norm}%",) + t_params
                ).fetchone()
            return dict(result) if result else None
        finally:
            if not self._conn:
                conn.close()

    def get_family_members(self, tenant_id: int = None) -> List[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            if tenant_id:
                results = conn.execute(
                    "SELECT * FROM family_members WHERE tenant_id = ? ORDER BY last_seen DESC",
                    (tenant_id,)
                ).fetchall()
            else:
                results = conn.execute(
                    "SELECT * FROM family_members ORDER BY last_seen DESC"
                ).fetchall()
            return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()

    def update_family_member(self, member_id: int, name: str = None,
                             relationship: str = None, relation_to_owner: str = None,
                             parent_member_id: int = None, generation: int = None) -> bool:
        conn = self._get_connection()
        try:
            updates = []
            params = []
            if name is not None:
                updates.append("name = ?")
                params.append(name)
                updates.append("name_normalized = ?")
                params.append(self._normalize(name))
            if relationship is not None:
                updates.append("relationship = ?")
                params.append(relationship)
            if relation_to_owner is not None:
                updates.append("relation_to_owner = ?")
                params.append(relation_to_owner)
            if parent_member_id is not None:
                updates.append("parent_member_id = ?")
                params.append(parent_member_id if parent_member_id > 0 else None)
            if generation is not None:
                updates.append("generation = ?")
                params.append(generation)
            if not updates:
                return False
            params.append(member_id)
            conn.execute(f"UPDATE family_members SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()
            return True
        finally:
            if not self._conn:
                conn.close()

    def get_family_member_by_id(self, member_id: int) -> Optional[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            result = conn.execute("SELECT * FROM family_members WHERE id = ?", (member_id,)).fetchone()
            return dict(result) if result else None
        finally:
            if not self._conn:
                conn.close()

    def delete_family_member(self, member_id: int) -> bool:
        conn = self._get_connection()
        try:
            # Clear parent references pointing to this member
            conn.execute("UPDATE family_members SET parent_member_id = NULL WHERE parent_member_id = ?", (member_id,))
            conn.execute("DELETE FROM family_members WHERE id = ?", (member_id,))
            conn.commit()
            return True
        finally:
            if not self._conn:
                conn.close()

    def update_family_member_visit(self, member_id: int):
        conn = self._get_connection()
        try:
            conn.execute("""
                UPDATE family_members SET visit_count = visit_count + 1,
                last_seen = CURRENT_TIMESTAMP WHERE id = ?
            """, (member_id,))
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def search_stories_by_speaker_or_topic(self, query: str, limit: int = 20,
                                           tenant_id: int = None) -> List[Dict]:
        query_norm = self._normalize(query)
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            t_clause = " AND s.tenant_id = ?" if tenant_id else ""
            t_params = (tenant_id,) if tenant_id else ()
            results = conn.execute(f"""
                SELECT s.* FROM stories s
                LEFT JOIN story_tags st ON s.id = st.story_id
                WHERE (s.speaker_name LIKE ? OR s.transcript LIKE ?
                   OR st.tag_value LIKE ?){t_clause}
                GROUP BY s.id ORDER BY s.created_at DESC LIMIT ?
            """, (f"%{query_norm}%", f"%{query_norm}%", f"%{query_norm}%") + t_params + (limit,)).fetchall()
            return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()

    def add_story_tag(self, story_id: int, tag_type: str, tag_value: str,
                      tenant_id: int = None) -> int:
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                INSERT INTO story_tags (story_id, tag_type, tag_value, tenant_id)
                VALUES (?, ?, ?, ?)
            """, (story_id, tag_type, tag_value, tenant_id))
            conn.commit()
            return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()

    # ── Structured memories ──

    def save_memory(self, story_id: int = None, speaker: str = None,
                    bucket: str = "ordinary_world", life_phase: str = "unknown",
                    text_summary: str = "", text: str = "",
                    people: list = None, locations: list = None,
                    emotions: list = None, fingerprint: str = None,
                    tenant_id: int = None) -> int:
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                INSERT INTO memories (story_id, speaker, bucket, life_phase,
                    text_summary, text, people, locations, emotions, fingerprint, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (story_id, speaker, bucket, life_phase, text_summary, text,
                  json.dumps(people or []),
                  json.dumps(locations or []),
                  json.dumps(emotions or []),
                  fingerprint, tenant_id))
            conn.commit()
            return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()

    def get_memories(self, speaker: str = None, bucket: str = None,
                     life_phase: str = None, verification_status: str = None,
                     limit: int = 200, tenant_id: int = None) -> List[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM memories WHERE 1=1"
            params = []
            if speaker:
                query += " AND speaker LIKE ?"
                params.append(f"%{speaker}%")
            if bucket:
                query += " AND bucket = ?"
                params.append(bucket)
            if life_phase:
                query += " AND life_phase = ?"
                params.append(life_phase)
            if verification_status:
                query += " AND verification_status = ?"
                params.append(verification_status)
            if tenant_id:
                query += " AND tenant_id = ?"
                params.append(tenant_id)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            results = conn.execute(query, params).fetchall()
            rows = []
            for r in results:
                d = dict(r)
                # Parse JSON fields
                for field in ("people", "locations", "emotions"):
                    try:
                        d[field] = json.loads(d[field]) if d[field] else []
                    except (json.JSONDecodeError, TypeError):
                        d[field] = []
                rows.append(d)
            return rows
        finally:
            if not self._conn:
                conn.close()

    def get_memory_by_id(self, memory_id: int) -> Optional[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            result = conn.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
            if not result:
                return None
            d = dict(result)
            for field in ("people", "locations", "emotions"):
                try:
                    d[field] = json.loads(d[field]) if d[field] else []
                except (json.JSONDecodeError, TypeError):
                    d[field] = []
            return d
        finally:
            if not self._conn:
                conn.close()

    def verify_memory(self, memory_id: int, verifier_name: str,
                      verifier_relationship: str = None,
                      status: str = "verified", notes: str = None) -> bool:
        conn = self._get_connection()
        try:
            conn.execute("""
                UPDATE memories SET verification_status = ?, verified_by = ?,
                verified_at = CURRENT_TIMESTAMP WHERE id = ?
            """, (status, verifier_name, memory_id))
            conn.execute("""
                INSERT INTO memory_verifications
                    (memory_id, verifier_name, verifier_relationship, status, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (memory_id, verifier_name, verifier_relationship, status, notes))
            conn.commit()
            return True
        finally:
            if not self._conn:
                conn.close()

    # ── Chapter drafts ──

    def save_chapter_draft(self, chapter_number: int, title: str,
                           bucket: str, life_phase: str,
                           memory_ids: str, content: str,
                           tenant_id: int = None) -> int:
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                INSERT INTO chapter_drafts
                    (chapter_number, title, bucket, life_phase, memory_ids, content, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (chapter_number, title, bucket, life_phase, memory_ids, content, tenant_id))
            conn.commit()
            return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()

    def get_chapter_drafts(self, tenant_id: int = None) -> List[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            if tenant_id:
                results = conn.execute(
                    "SELECT * FROM chapter_drafts WHERE tenant_id = ? ORDER BY chapter_number",
                    (tenant_id,)
                ).fetchall()
            else:
                results = conn.execute(
                    "SELECT * FROM chapter_drafts ORDER BY chapter_number"
                ).fetchall()
            return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()

    # ── User profiles ──

    def get_or_create_user(self, name: str = "Default User",
                           tenant_id: int = None) -> Dict:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            if tenant_id:
                user = conn.execute(
                    "SELECT * FROM user_profiles WHERE tenant_id = ? LIMIT 1",
                    (tenant_id,)
                ).fetchone()
            else:
                user = conn.execute("SELECT * FROM user_profiles LIMIT 1").fetchone()
            if user:
                return dict(user)
            cursor = conn.execute(
                "INSERT INTO user_profiles (name, tenant_id) VALUES (?, ?)",
                (name, tenant_id)
            )
            conn.commit()
            user = conn.execute(
                "SELECT * FROM user_profiles WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return dict(user)
        finally:
            if not self._conn:
                conn.close()

    def update_user_setup(self, user_id: int, name: str, owner_email: str,
                          caretaker_name: str, caretaker_email: str) -> None:
        conn = self._get_connection()
        try:
            conn.execute("""
                UPDATE user_profiles SET name = ?, owner_email = ?,
                caretaker_name = ?, caretaker_email = ?,
                setup_complete = 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (name, owner_email or None, caretaker_name or None,
                  caretaker_email or None, user_id))
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def get_owner_name(self, tenant_id: int = None) -> str:
        """Get the owner's name from user_profiles, or fallback."""
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            if tenant_id:
                user = conn.execute(
                    "SELECT name FROM user_profiles WHERE tenant_id = ? LIMIT 1",
                    (tenant_id,)
                ).fetchone()
            else:
                user = conn.execute("SELECT name FROM user_profiles LIMIT 1").fetchone()
            return user["name"] if user else None
        finally:
            if not self._conn:
                conn.close()

    # ── Story verification ──

    def get_story_by_id(self, story_id: int) -> Optional[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            result = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
            return dict(result) if result else None
        finally:
            if not self._conn:
                conn.close()

    def verify_story(self, story_id: int, verified_by: str,
                     corrected_transcript: str = None) -> bool:
        conn = self._get_connection()
        try:
            if corrected_transcript:
                conn.execute("""
                    UPDATE stories SET verified = 1, verified_by = ?,
                    verified_at = CURRENT_TIMESTAMP, corrected_transcript = ?
                    WHERE id = ?
                """, (verified_by, corrected_transcript, story_id))
            else:
                conn.execute("""
                    UPDATE stories SET verified = 1, verified_by = ?,
                    verified_at = CURRENT_TIMESTAMP WHERE id = ?
                """, (verified_by, story_id))
            conn.commit()
            return True
        finally:
            if not self._conn:
                conn.close()

    # ── Photos ──

    def save_photo(self, filename: str, original_name: str = None,
                   caption: str = None, date_taken: str = None,
                   tags: str = "[]", story_id: int = None,
                   uploaded_by: str = None, user_id: int = None,
                   tenant_id: int = None) -> int:
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                INSERT INTO photos (user_id, filename, original_name, caption,
                    date_taken, tags, story_id, uploaded_by, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, filename, original_name, caption, date_taken,
                  tags, story_id, uploaded_by, tenant_id))
            conn.commit()
            return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()

    def get_photos(self, limit: int = 100, tenant_id: int = None) -> List[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            if tenant_id:
                results = conn.execute(
                    "SELECT * FROM photos WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
                    (tenant_id, limit)
                ).fetchall()
            else:
                results = conn.execute(
                    "SELECT * FROM photos ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()

    def get_photo_by_id(self, photo_id: int) -> Optional[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            result = conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
            return dict(result) if result else None
        finally:
            if not self._conn:
                conn.close()

    def update_photo(self, photo_id: int, caption: str = None,
                     date_taken: str = None, tags: str = None,
                     story_id: int = None) -> bool:
        conn = self._get_connection()
        try:
            conn.execute("""
                UPDATE photos SET caption = ?, date_taken = ?, tags = ?,
                story_id = ? WHERE id = ?
            """, (caption, date_taken, tags, story_id, photo_id))
            conn.commit()
            return True
        finally:
            if not self._conn:
                conn.close()

    def get_photos_by_tag(self, tag: str, tenant_id: int = None) -> List[Dict]:
        """Find photos whose JSON tags array contains the given tag (case-insensitive)."""
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            tag_lower = tag.lower()
            if tenant_id:
                results = conn.execute(
                    "SELECT * FROM photos WHERE LOWER(tags) LIKE ? AND tenant_id = ? ORDER BY created_at DESC",
                    (f'%"{tag_lower}"%', tenant_id)
                ).fetchall()
            else:
                results = conn.execute(
                    "SELECT * FROM photos WHERE LOWER(tags) LIKE ? ORDER BY created_at DESC",
                    (f'%"{tag_lower}"%',)
                ).fetchall()
            return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()

    def link_photo_story(self, photo_id: int, story_id: int) -> bool:
        conn = self._get_connection()
        try:
            conn.execute("UPDATE photos SET story_id = ? WHERE id = ?", (story_id, photo_id))
            conn.commit()
            return True
        finally:
            if not self._conn:
                conn.close()

    def delete_photo(self, photo_id: int) -> bool:
        conn = self._get_connection()
        try:
            cursor = conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if not self._conn:
                conn.close()

    # ── Family Message Board ──

    def save_message(self, from_name: str, message: str, to_name: str = None,
                     tenant_id: int = None, expire_hours: int = 24) -> int:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """INSERT INTO family_messages (tenant_id, from_name, to_name, message, expires_at)
                   VALUES (?, ?, ?, ?, datetime('now', ?))""",
                (tenant_id, from_name, to_name, message, f"+{expire_hours} hours")
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()

    def get_messages_for(self, name: str = None, tenant_id: int = None) -> list:
        """Get unread/active messages, optionally filtered by recipient."""
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            t_clause = " AND tenant_id = ?" if tenant_id else ""
            t_params = (tenant_id,) if tenant_id else ()
            if name:
                name_lower = name.lower()
                results = conn.execute(
                    f"""SELECT * FROM family_messages
                        WHERE (to_name IS NULL OR LOWER(to_name) = ?)
                        AND expires_at > datetime('now')
                        {t_clause}
                        ORDER BY created_at DESC""",
                    (name_lower,) + t_params
                ).fetchall()
            else:
                results = conn.execute(
                    f"""SELECT * FROM family_messages
                        WHERE expires_at > datetime('now')
                        {t_clause}
                        ORDER BY created_at DESC""",
                    t_params
                ).fetchall()
            return [dict(r) for r in results]
        finally:
            if not self._conn:
                conn.close()

    def get_person_status(self, name: str, tenant_id: int = None) -> dict:
        """Get the most recent message FROM a person (their status)."""
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            t_clause = " AND tenant_id = ?" if tenant_id else ""
            t_params = (tenant_id,) if tenant_id else ()
            result = conn.execute(
                f"""SELECT * FROM family_messages
                    WHERE LOWER(from_name) = ?
                    AND expires_at > datetime('now')
                    {t_clause}
                    ORDER BY created_at DESC LIMIT 1""",
                (name.lower(),) + t_params
            ).fetchone()
            return dict(result) if result else None
        finally:
            if not self._conn:
                conn.close()

    def clear_person_messages(self, from_name: str, tenant_id: int = None):
        """Clear all messages from a person (they're back home)."""
        conn = self._get_connection()
        try:
            t_clause = " AND tenant_id = ?" if tenant_id else ""
            t_params = (tenant_id,) if tenant_id else ()
            conn.execute(
                f"DELETE FROM family_messages WHERE LOWER(from_name) = ?{t_clause}",
                (from_name.lower(),) + t_params
            )
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def delete_message(self, message_id: int, tenant_id: int = None):
        """Delete a single message by ID."""
        conn = self._get_connection()
        try:
            t_clause = " AND tenant_id = ?" if tenant_id else ""
            t_params = (tenant_id,) if tenant_id else ()
            conn.execute(
                f"DELETE FROM family_messages WHERE id = ?{t_clause}",
                (message_id,) + t_params
            )
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def clear_all_messages(self, tenant_id: int = None):
        """Delete all messages for a tenant."""
        conn = self._get_connection()
        try:
            if tenant_id:
                conn.execute("DELETE FROM family_messages WHERE tenant_id = ?", (tenant_id,))
            else:
                conn.execute("DELETE FROM family_messages")
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    # ── Firmware OTA management ──

    def update_device_firmware_info(self, device_id: str, fw_version: str, fw_variant: str):
        conn = self._get_connection()
        try:
            conn.execute(
                "UPDATE devices SET fw_version = ?, fw_variant = ? WHERE device_id = ?",
                (fw_version, fw_variant, device_id)
            )
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def save_firmware_version(self, variant: str, version: str, filename: str,
                              file_size: int, file_hash: str, release_notes: str = None) -> int:
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                INSERT INTO firmware_versions (variant, version, filename, file_size, file_hash, release_notes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (variant, version, filename, file_size, file_hash, release_notes))
            conn.commit()
            return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()

    def get_firmware_versions(self, variant: str = None) -> List[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            if variant:
                rows = conn.execute(
                    "SELECT * FROM firmware_versions WHERE variant = ? ORDER BY uploaded_at DESC",
                    (variant,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM firmware_versions ORDER BY uploaded_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            if not self._conn:
                conn.close()

    def get_active_firmware(self, variant: str) -> Optional[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            result = conn.execute(
                "SELECT * FROM firmware_versions WHERE variant = ? AND is_active = 1",
                (variant,)
            ).fetchone()
            return dict(result) if result else None
        finally:
            if not self._conn:
                conn.close()

    def get_firmware_by_id(self, firmware_id: int) -> Optional[Dict]:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            result = conn.execute(
                "SELECT * FROM firmware_versions WHERE id = ?", (firmware_id,)
            ).fetchone()
            return dict(result) if result else None
        finally:
            if not self._conn:
                conn.close()

    def set_active_firmware(self, firmware_id: int):
        conn = self._get_connection()
        try:
            # Get variant of the target firmware
            row = conn.execute("SELECT variant FROM firmware_versions WHERE id = ?", (firmware_id,)).fetchone()
            if not row:
                return
            variant = row[0]
            # Deactivate all for this variant, then activate the target
            conn.execute("UPDATE firmware_versions SET is_active = 0 WHERE variant = ?", (variant,))
            conn.execute("UPDATE firmware_versions SET is_active = 1 WHERE id = ?", (firmware_id,))
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def delete_firmware_version(self, firmware_id: int) -> Optional[str]:
        """Delete a firmware version. Returns filename if deleted, None if active."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT filename, is_active FROM firmware_versions WHERE id = ?", (firmware_id,)
            ).fetchone()
            if not row:
                return None
            if row[1] == 1:
                return None  # Can't delete active firmware
            conn.execute("DELETE FROM firmware_versions WHERE id = ?", (firmware_id,))
            conn.commit()
            return row[0]
        finally:
            if not self._conn:
                conn.close()
