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

            # ── Narrative log (track which stories were read back) ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS narrative_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER,
                    story_id INTEGER REFERENCES stories(id),
                    query TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_narrative_log_tenant ON narrative_log(tenant_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_narrative_log_story ON narrative_log(story_id, created_at)")

            # ── Story narratives (cached GPT narratives for replay) ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS story_narratives (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER,
                    narrative TEXT NOT NULL,
                    attribution TEXT,
                    story_ids TEXT,
                    query TEXT,
                    status TEXT DEFAULT 'draft',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── Device events (admin telemetry) ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS device_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    tenant_id INTEGER,
                    event_type TEXT NOT NULL,
                    intent TEXT,
                    success INTEGER DEFAULT 1,
                    detail TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_device_events_device_time ON device_events(device_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_device_events_type_time ON device_events(event_type, created_at)")

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
                "location_city": "ALTER TABLE user_profiles ADD COLUMN location_city TEXT",
                "location_lat": "ALTER TABLE user_profiles ADD COLUMN location_lat REAL",
                "location_lon": "ALTER TABLE user_profiles ADD COLUMN location_lon REAL",
                "squawk_volume": "ALTER TABLE user_profiles ADD COLUMN squawk_volume INTEGER DEFAULT 30",
                "rms_threshold": "ALTER TABLE user_profiles ADD COLUMN rms_threshold INTEGER DEFAULT 200",
                "hometown": "ALTER TABLE user_profiles ADD COLUMN hometown TEXT",
                "birth_year": "ALTER TABLE user_profiles ADD COLUMN birth_year INTEGER",
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
                "photo_in_book": "ALTER TABLE stories ADD COLUMN photo_in_book INTEGER DEFAULT 1",
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

            # Add is_admin to accounts
            cols = {row[1] for row in conn.execute("PRAGMA table_info(accounts)").fetchall()}
            if "is_admin" not in cols:
                conn.execute("ALTER TABLE accounts ADD COLUMN is_admin INTEGER DEFAULT 0")
                # First account is always admin (manufacturer)
                conn.execute("UPDATE accounts SET is_admin = 1 WHERE id = 1")

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

            # Add extended info to family_members
            cols = {row[1] for row in conn.execute("PRAGMA table_info(family_members)").fetchall()}
            fm_ext = {
                "deceased": "ALTER TABLE family_members ADD COLUMN deceased INTEGER DEFAULT 0",
                "spouse_name": "ALTER TABLE family_members ADD COLUMN spouse_name TEXT",
                "bio": "ALTER TABLE family_members ADD COLUMN bio TEXT",
                "added_by": "ALTER TABLE family_members ADD COLUMN added_by TEXT",
                "birth_year": "ALTER TABLE family_members ADD COLUMN birth_year INTEGER",
            }
            for col, sql in fm_ext.items():
                if col not in cols:
                    conn.execute(sql)

            # Add estimated_year to memories for timeline tracking
            cols = {row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()}
            if "estimated_year" not in cols:
                conn.execute("ALTER TABLE memories ADD COLUMN estimated_year INTEGER")

            # Prayer requests table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prayer_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER,
                    name TEXT NOT NULL,
                    request TEXT,
                    active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Pronunciation guide table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pronunciations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER,
                    word TEXT NOT NULL,
                    phonetic TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Nostalgia snippets table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS nostalgia_snippets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER,
                    category TEXT NOT NULL,
                    variation_number INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    last_used TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_nostalgia_tenant ON nostalgia_snippets(tenant_id)")

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
                       a.role as account_role, a.is_admin as account_is_admin,
                       ws.role as session_role, ws.family_name
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
                             parent_member_id: int = None, generation: int = None,
                             deceased: int = None, spouse_name: str = None,
                             bio: str = None, added_by: str = None,
                             birth_year: int = None) -> bool:
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
            if deceased is not None:
                updates.append("deceased = ?")
                params.append(deceased)
            if spouse_name is not None:
                updates.append("spouse_name = ?")
                params.append(spouse_name if spouse_name.strip() else None)
            if bio is not None:
                updates.append("bio = ?")
                params.append(bio if bio.strip() else None)
            if added_by is not None:
                updates.append("added_by = ?")
                params.append(added_by if added_by.strip() else None)
            if birth_year is not None:
                updates.append("birth_year = ?")
                params.append(birth_year if birth_year > 0 else None)
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

    # ── Narrative log ──

    # ── Prayer requests ──

    def add_prayer_request(self, name: str, request: str = None,
                           tenant_id: int = None) -> int:
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                INSERT INTO prayer_requests (tenant_id, name, request)
                VALUES (?, ?, ?)
            """, (tenant_id, name, request))
            conn.commit()
            return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()

    def get_prayer_requests(self, tenant_id: int, active_only: bool = True) -> list:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            if active_only:
                rows = conn.execute(
                    "SELECT * FROM prayer_requests WHERE tenant_id = ? AND active = 1 ORDER BY created_at DESC",
                    (tenant_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM prayer_requests WHERE tenant_id = ? ORDER BY created_at DESC",
                    (tenant_id,)
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            if not self._conn:
                conn.close()

    def delete_prayer_request(self, request_id: int):
        conn = self._get_connection()
        try:
            conn.execute("DELETE FROM prayer_requests WHERE id = ?", (request_id,))
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    # ── Pronunciation guide ──

    def get_pronunciations(self, tenant_id: int) -> list:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM pronunciations WHERE tenant_id = ? ORDER BY word",
                (tenant_id,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            if not self._conn:
                conn.close()

    def add_pronunciation(self, tenant_id: int, word: str, phonetic: str) -> int:
        conn = self._get_connection()
        try:
            # Upsert: if same word exists for this tenant, update it
            existing = conn.execute(
                "SELECT id FROM pronunciations WHERE tenant_id = ? AND LOWER(word) = LOWER(?)",
                (tenant_id, word)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE pronunciations SET phonetic = ? WHERE id = ?",
                    (phonetic, existing[0])
                )
                conn.commit()
                return existing[0]
            cursor = conn.execute(
                "INSERT INTO pronunciations (tenant_id, word, phonetic) VALUES (?, ?, ?)",
                (tenant_id, word, phonetic)
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()

    def delete_pronunciation(self, pronunciation_id: int):
        conn = self._get_connection()
        try:
            conn.execute("DELETE FROM pronunciations WHERE id = ?", (pronunciation_id,))
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    # ── Nostalgia snippets ──

    def get_nostalgia_snippets(self, tenant_id: int, category: str = None) -> list:
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            if category:
                rows = conn.execute(
                    "SELECT * FROM nostalgia_snippets WHERE tenant_id = ? AND category = ? ORDER BY category, variation_number",
                    (tenant_id, category)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM nostalgia_snippets WHERE tenant_id = ? ORDER BY category, variation_number",
                    (tenant_id,)
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            if not self._conn:
                conn.close()

    def get_next_nostalgia_snippet(self, tenant_id: int) -> dict:
        """Get the next snippet to play (oldest last_used first, unused first)."""
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute("""
                SELECT * FROM nostalgia_snippets WHERE tenant_id = ?
                ORDER BY last_used IS NOT NULL, last_used ASC, RANDOM()
                LIMIT 1
            """, (tenant_id,)).fetchone()
            return dict(row) if row else None
        finally:
            if not self._conn:
                conn.close()

    def save_nostalgia_snippets(self, tenant_id: int, snippets: list):
        """Bulk save snippets (replaces all existing for tenant)."""
        conn = self._get_connection()
        try:
            conn.execute("DELETE FROM nostalgia_snippets WHERE tenant_id = ?", (tenant_id,))
            for s in snippets:
                conn.execute("""
                    INSERT INTO nostalgia_snippets (tenant_id, category, variation_number, text)
                    VALUES (?, ?, ?, ?)
                """, (tenant_id, s["category"], s["variation"], s["text"]))
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def update_nostalgia_snippet(self, snippet_id: int, text: str):
        conn = self._get_connection()
        try:
            conn.execute("UPDATE nostalgia_snippets SET text = ? WHERE id = ?", (text, snippet_id))
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def delete_nostalgia_snippet(self, snippet_id: int):
        conn = self._get_connection()
        try:
            conn.execute("DELETE FROM nostalgia_snippets WHERE id = ?", (snippet_id,))
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def mark_nostalgia_used(self, snippet_id: int):
        conn = self._get_connection()
        try:
            conn.execute("UPDATE nostalgia_snippets SET last_used = CURRENT_TIMESTAMP WHERE id = ?", (snippet_id,))
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def log_narrative_stories(self, story_ids: list, tenant_id: int = None,
                              query: str = None):
        """Log which stories were used in a narrative reading."""
        conn = self._get_connection()
        try:
            for sid in story_ids:
                conn.execute("""
                    INSERT INTO narrative_log (tenant_id, story_id, query)
                    VALUES (?, ?, ?)
                """, (tenant_id, sid, query))
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def get_recently_narrated_story_ids(self, tenant_id: int, days: int = 7) -> set:
        """Get story IDs that were used in narratives within the last N days."""
        conn = self._get_connection()
        try:
            rows = conn.execute("""
                SELECT DISTINCT story_id FROM narrative_log
                WHERE tenant_id = ? AND created_at > datetime('now', ?)
            """, (tenant_id, f"-{days} days")).fetchall()
            return {r[0] for r in rows}
        finally:
            if not self._conn:
                conn.close()

    def get_story_last_narrated(self, tenant_id: int) -> dict:
        """Return {story_id: last_narrated_timestamp} for all stories ever narrated."""
        conn = self._get_connection()
        try:
            rows = conn.execute("""
                SELECT story_id, MAX(created_at) as last_used
                FROM narrative_log WHERE tenant_id = ?
                GROUP BY story_id
            """, (tenant_id,)).fetchall()
            return {r[0]: r[1] for r in rows}
        finally:
            if not self._conn:
                conn.close()

    # ── Story narratives (cached) ──

    def save_narrative(self, tenant_id: int, narrative: str, attribution: str = None,
                       story_ids: list = None, query: str = None) -> int:
        """Save a GPT-generated narrative for potential replay."""
        conn = self._get_connection()
        try:
            ids_str = ",".join(str(s) for s in story_ids) if story_ids else None
            cursor = conn.execute("""
                INSERT INTO story_narratives (tenant_id, narrative, attribution, story_ids, query)
                VALUES (?, ?, ?, ?, ?)
            """, (tenant_id, narrative, attribution, ids_str, query))
            conn.commit()
            return cursor.lastrowid
        finally:
            if not self._conn:
                conn.close()

    def get_narratives(self, tenant_id: int, status: str = None) -> list:
        """Get saved narratives, optionally filtered by status."""
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            if status:
                rows = conn.execute(
                    "SELECT * FROM story_narratives WHERE tenant_id = ? AND status = ? ORDER BY created_at DESC",
                    (tenant_id, status)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM story_narratives WHERE tenant_id = ? ORDER BY created_at DESC",
                    (tenant_id,)
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            if not self._conn:
                conn.close()

    def get_narrative(self, narrative_id: int) -> dict:
        """Get a single narrative by ID."""
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM story_narratives WHERE id = ?", (narrative_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            if not self._conn:
                conn.close()

    def get_kept_narrative_for_stories(self, tenant_id: int, story_ids: list) -> dict:
        """Find a kept narrative that uses the same story IDs."""
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            ids_str = ",".join(str(s) for s in sorted(story_ids))
            row = conn.execute(
                "SELECT * FROM story_narratives WHERE tenant_id = ? AND status = 'kept' AND story_ids = ? ORDER BY created_at DESC LIMIT 1",
                (tenant_id, ids_str)
            ).fetchone()
            return dict(row) if row else None
        finally:
            if not self._conn:
                conn.close()

    def update_narrative(self, narrative_id: int, narrative: str = None, status: str = None):
        """Update a narrative's text and/or status."""
        conn = self._get_connection()
        try:
            if narrative is not None and status is not None:
                conn.execute("UPDATE story_narratives SET narrative = ?, status = ? WHERE id = ?",
                             (narrative, status, narrative_id))
            elif narrative is not None:
                conn.execute("UPDATE story_narratives SET narrative = ? WHERE id = ?",
                             (narrative, narrative_id))
            elif status is not None:
                conn.execute("UPDATE story_narratives SET status = ? WHERE id = ?",
                             (status, narrative_id))
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def delete_narrative(self, narrative_id: int):
        """Delete a narrative."""
        conn = self._get_connection()
        try:
            conn.execute("DELETE FROM story_narratives WHERE id = ?", (narrative_id,))
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def auto_tag_story(self, story_id: int, transcript: str, tenant_id: int = None):
        """Extract and save people, places, year tags from transcript.
        Also estimates year from relative date phrases + speaker birth_year."""
        if not transcript:
            return
        import re
        conn = self._get_connection()
        try:
            # Check existing tags to avoid duplicates
            existing = {(r[0], r[1]) for r in conn.execute(
                "SELECT tag_type, tag_value FROM story_tags WHERE story_id = ?",
                (story_id,)
            ).fetchall()}

            tags = []
            text_lower = transcript.lower()
            explicit_years = []

            # Years (4-digit numbers between 1900-2030)
            for m in re.finditer(r'\b(19\d{2}|20[0-2]\d)\b', transcript):
                yr = m.group(1)
                tags.append(("year", yr))
                explicit_years.append(int(yr))

            # People — match against known family members
            if tenant_id:
                members = conn.execute(
                    "SELECT name FROM family_members WHERE tenant_id = ?",
                    (tenant_id,)
                ).fetchall()
                for (name,) in members:
                    if name and name.lower() in text_lower:
                        tags.append(("person", name))

            # Also tag the speaker if set on the story
            speaker_row = conn.execute(
                "SELECT speaker_name FROM stories WHERE id = ?", (story_id,)
            ).fetchone()
            speaker_name = speaker_row[0] if speaker_row and speaker_row[0] else None
            if speaker_name:
                tags.append(("person", speaker_name))

            # Common place indicators
            place_patterns = [
                r'\bin\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
                r'\bat\s+(?:the\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
                r'\bfrom\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
            ]
            for pat in place_patterns:
                for m in re.finditer(pat, transcript):
                    val = m.group(1).strip()
                    if len(val) > 2 and val.lower() not in (
                        "the", "and", "but", "was", "were", "had", "has",
                        "that", "this", "there", "then", "when", "where",
                    ):
                        tags.append(("place", val))

            for tag_type, tag_value in tags:
                if (tag_type, tag_value) not in existing:
                    conn.execute("""
                        INSERT INTO story_tags (story_id, tag_type, tag_value, tenant_id)
                        VALUES (?, ?, ?, ?)
                    """, (story_id, tag_type, tag_value, tenant_id))

            # ── Estimate year from relative date phrases + birth_year ──
            estimated_year = None

            # If we found explicit years, use the first one
            if explicit_years:
                estimated_year = explicit_years[0]
            elif tenant_id:
                # Look up speaker's birth_year
                speaker_birth_year = self._get_speaker_birth_year(
                    conn, speaker_name, tenant_id
                )
                if speaker_birth_year:
                    estimated_year = self._estimate_year_from_phrases(
                        text_lower, speaker_birth_year
                    )

            # Also check for direct decade references ("back in the 60s")
            if not estimated_year:
                decade_match = re.search(
                    r'\b(?:in|back in|during)\s+the\s+[\'"]?(\d{2})s\b', text_lower
                )
                if decade_match:
                    decade = int(decade_match.group(1))
                    # 20s-90s = 1920s-1990s, 00s-10s = 2000s-2010s
                    if decade >= 20:
                        estimated_year = 1900 + decade + 5  # midpoint
                    else:
                        estimated_year = 2000 + decade + 5

            # Save estimated year to the memory linked to this story
            if estimated_year:
                if ("year", str(estimated_year)) not in existing:
                    conn.execute("""
                        INSERT INTO story_tags (story_id, tag_type, tag_value, tenant_id)
                        VALUES (?, ?, ?, ?)
                    """, (story_id, "year", str(estimated_year), tenant_id))
                # Update the memory's estimated_year
                conn.execute("""
                    UPDATE memories SET estimated_year = ?
                    WHERE story_id = ? AND estimated_year IS NULL
                """, (estimated_year, story_id))

            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def _get_speaker_birth_year(self, conn, speaker_name: str,
                                tenant_id: int) -> Optional[int]:
        """Look up a speaker's birth year from user_profiles or family_members."""
        if not speaker_name:
            return None
        speaker_lower = speaker_name.lower().strip()

        # Check if speaker is the owner (user_profiles)
        owner = conn.execute(
            "SELECT name, birth_year FROM user_profiles WHERE tenant_id = ? LIMIT 1",
            (tenant_id,)
        ).fetchone()
        if owner and owner[1]:
            owner_name = (owner[0] or "").lower().strip()
            if owner_name and (speaker_lower == owner_name
                               or speaker_lower in owner_name
                               or owner_name in speaker_lower):
                return owner[1]

        # Check family_members
        member = conn.execute(
            "SELECT birth_year FROM family_members WHERE tenant_id = ? AND birth_year IS NOT NULL AND LOWER(name) = ?",
            (tenant_id, speaker_lower)
        ).fetchone()
        if member and member[0]:
            return member[0]

        return None

    @staticmethod
    def _estimate_year_from_phrases(text_lower: str, birth_year: int) -> Optional[int]:
        """Estimate a calendar year from relative date phrases + birth_year."""
        # Ordered by specificity — first match wins
        PHRASE_MAP = [
            # Specific ages / life stages
            (r'\b(?:when i was|as) a (?:little )?(?:kid|child|boy|girl)\b', 8),
            (r'\b(?:growing up|childhood|as a child)\b', 10),
            (r'\b(?:in (?:grade|elementary) school)\b', 10),
            (r'\b(?:in (?:middle|junior high) school)\b', 13),
            (r'\b(?:in high school|as a teenager|teenage years)\b', 16),
            (r'\b(?:in college|at university|in my twenties)\b', 22),
            (r'\b(?:when (?:we|i) got married|newlywed|wedding day)\b', 25),
            (r'\b(?:when the kids were (?:little|young|small|born))\b', 32),
            (r'\b(?:in my thirties)\b', 35),
            (r'\b(?:in my forties|middle.?aged?)\b', 45),
            (r'\b(?:in my fifties)\b', 55),
            (r'\b(?:in my sixties)\b', 65),
            (r'\b(?:after (?:i )?retired|in retirement)\b', 65),
            # Vaguer references
            (r'\b(?:when i was young|back then|years ago|long time ago)\b', 15),
            (r'\b(?:during the war)\b', 22),  # generic — assumes young adult
        ]
        import re
        for pattern, age_offset in PHRASE_MAP:
            if re.search(pattern, text_lower):
                return birth_year + age_offset
        return None

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

    # ── Admin dashboard (cross-tenant) ──

    def log_device_event(self, device_id: str, tenant_id: int,
                         event_type: str, intent: str = None,
                         success: int = 1, detail: str = None):
        """Insert a device event row for admin telemetry."""
        conn = self._get_connection()
        try:
            conn.execute(
                """INSERT INTO device_events
                   (device_id, tenant_id, event_type, intent, success, detail)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (device_id, tenant_id, event_type, intent, success, detail),
            )
            conn.commit()
        finally:
            if not self._conn:
                conn.close()

    def get_admin_dashboard_stats(self) -> Dict:
        """Cross-tenant stats for the admin dashboard."""
        conn = self._get_connection()
        try:
            total_devices = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
            # Online = last_seen within 5 minutes
            online_devices = conn.execute(
                "SELECT COUNT(*) FROM devices WHERE last_seen > datetime('now', '-5 minutes')"
            ).fetchone()[0]
            total_tenants = conn.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]
            total_stories = conn.execute("SELECT COUNT(*) FROM stories").fetchone()[0]
            total_stories_today = conn.execute(
                "SELECT COUNT(*) FROM stories WHERE created_at > datetime('now', '-1 day')"
            ).fetchone()[0]
            total_commands_today = conn.execute(
                "SELECT COUNT(*) FROM device_events WHERE event_type = 'command' AND created_at > datetime('now', '-1 day')"
            ).fetchone()[0]
            total_errors_today = conn.execute(
                "SELECT COUNT(*) FROM device_events WHERE event_type = 'error' AND created_at > datetime('now', '-1 day')"
            ).fetchone()[0]
            return {
                "total_devices": total_devices,
                "online_devices": online_devices,
                "total_tenants": total_tenants,
                "total_stories": total_stories,
                "total_stories_today": total_stories_today,
                "total_commands_today": total_commands_today,
                "total_errors_today": total_errors_today,
            }
        finally:
            if not self._conn:
                conn.close()

    def get_admin_device_list(self) -> List[Dict]:
        """All devices with tenant name, firmware info, and event counts."""
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT d.device_id, d.name, d.last_seen, d.fw_version, d.fw_variant,
                       d.tenant_id, t.name AS tenant_name,
                       (SELECT COUNT(*) FROM device_events e
                        WHERE e.device_id = d.device_id AND e.event_type = 'command'
                        AND e.created_at > datetime('now', '-1 day')) AS commands_today,
                       (SELECT COUNT(*) FROM device_events e
                        WHERE e.device_id = d.device_id AND e.event_type = 'error'
                        AND e.created_at > datetime('now', '-1 day')) AS errors_today,
                       (SELECT COUNT(*) FROM stories s
                        WHERE s.tenant_id = d.tenant_id) AS stories_total,
                       (SELECT e.created_at FROM device_events e
                        WHERE e.device_id = d.device_id AND e.event_type = 'command'
                        ORDER BY e.created_at DESC LIMIT 1) AS last_command
                FROM devices d
                LEFT JOIN tenants t ON d.tenant_id = t.id
                ORDER BY d.last_seen DESC
            """).fetchall()
            return [dict(r) for r in rows]
        finally:
            if not self._conn:
                conn.close()

    def get_admin_intent_stats(self, days: int = 7) -> List[Dict]:
        """Intent usage counts for the last N days, ordered by count DESC."""
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT intent, COUNT(*) AS cnt
                   FROM device_events
                   WHERE event_type = 'command' AND intent IS NOT NULL
                     AND created_at > datetime('now', ? || ' days')
                   GROUP BY intent
                   ORDER BY cnt DESC""",
                (f"-{days}",),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            if not self._conn:
                conn.close()

    def get_admin_error_log(self, limit: int = 50) -> List[Dict]:
        """Recent error events with device_id and detail."""
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT device_id, tenant_id, detail, created_at
                   FROM device_events
                   WHERE event_type = 'error'
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            if not self._conn:
                conn.close()
