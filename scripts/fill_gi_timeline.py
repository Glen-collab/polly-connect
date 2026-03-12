"""
Fill in birth years for Gi Lee's family tree (tenant_id=2)
and set owner profile birth_year/hometown.
Then re-run auto_tag_story on all stories to populate estimated_year.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3

conn = sqlite3.connect('polly.db')
conn.row_factory = sqlite3.Row

# ── Set owner profile ──
conn.execute("""
    UPDATE user_profiles SET birth_year = 1952, hometown = 'San Francisco, California'
    WHERE tenant_id = 2
""")
print("Set Gi Lee: born 1952, hometown San Francisco")

# ── Family member birth years ──
# Derived from bios, year tags, and story context
BIRTH_YEARS = {
    "Wei Lee": 1900,            # immigrated 1920s, grandfather
    "Mei-Hua Lee": 1902,        # Wei's wife, grandmother
    "James Lee": 1925,          # first-gen American, father
    "Lian Lee": 1928,           # mother, seamstress
    "David Lee": 1930,          # Jin's younger brother, traveled Japan 1960s
    "Rose Lee": 1932,           # David's wife, aunt
    "Master Chen Wei-Ming": 1920,  # taught Gi from age 12 (~1964), passed 2000
    "Mrs. Dorothy Patterson": 1924,  # passed 2018 at 94
    "Sarah Chen": 1958,         # met Gi 1984, married 1985
    "Tommy Lee": 1952,          # same age as Gi per bio
    "Ray Tanaka": 1952,         # met Gi at first tournament age 16
    "Tom Chen": 1955,           # Sarah's brother, firefighter
    "Lily Lee": 1988,           # born 1988 per bio
    "Marcus Lee": 1991,         # born 1991 per bio
    "Daniel Lee": 1991,         # born 1991, Marcus's twin
    "Mike Santos": 1970,        # first student 1986, troubled teenager
}

for name, year in BIRTH_YEARS.items():
    result = conn.execute(
        "UPDATE family_members SET birth_year = ? WHERE tenant_id = 2 AND name = ?",
        (year, name)
    )
    status = "OK" if result.rowcount > 0 else "NOT FOUND"
    print(f"  {name:30s}  born {year}  [{status}]")

conn.commit()

# ── Re-run auto_tag_story on all stories to populate estimated_year ──
from server.core.database import PollyDB
db = PollyDB.__new__(PollyDB)
db._conn = conn
db.db_path = 'polly.db'

stories = conn.execute(
    "SELECT id, transcript, speaker_name FROM stories WHERE tenant_id = 2 AND transcript IS NOT NULL"
).fetchall()

updated = 0
for story in stories:
    sid = story["id"]
    transcript = story["transcript"]
    if not transcript:
        continue
    db.auto_tag_story(sid, transcript, tenant_id=2)
    # Check if estimated_year was set
    mem = conn.execute(
        "SELECT estimated_year FROM memories WHERE story_id = ? AND estimated_year IS NOT NULL",
        (sid,)
    ).fetchone()
    if mem:
        updated += 1

print(f"\nRe-tagged {len(stories)} stories, {updated} now have estimated_year")

# Show results
mems = conn.execute(
    "SELECT m.estimated_year, m.life_phase, m.speaker, s.transcript "
    "FROM memories m JOIN stories s ON m.story_id = s.id "
    "WHERE m.tenant_id = 2 AND m.estimated_year IS NOT NULL "
    "ORDER BY m.estimated_year"
).fetchall()
print(f"\n=== MEMORIES WITH ESTIMATED YEAR ({len(mems)}) ===")
for m in mems:
    t = (m["transcript"] or "")[:70]
    print(f"  ~{m['estimated_year']}  {m['life_phase']:15s}  {m['speaker']:15s}  {t}")

conn.close()
