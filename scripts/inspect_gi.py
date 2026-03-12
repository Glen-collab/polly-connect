"""Inspect Gi Lee's tenant data for timeline filling."""
import sqlite3
import json

conn = sqlite3.connect('polly.db')
conn.row_factory = sqlite3.Row

# Owner profile
profile = conn.execute('SELECT id, name, birth_year, hometown FROM user_profiles WHERE tenant_id = 2').fetchone()
print('=== OWNER PROFILE ===')
if profile:
    print(f'  id={profile["id"]}  name={profile["name"]}  birth_year={profile["birth_year"]}  hometown={profile["hometown"]}')

# Family members
members = conn.execute('SELECT id, name, relation_to_owner, generation, birth_year, deceased, spouse_name, bio FROM family_members WHERE tenant_id = 2 ORDER BY generation, name').fetchall()
print(f'\n=== FAMILY MEMBERS ({len(members)} total) ===')
for m in members:
    nm = m["name"] or ""
    rel = m["relation_to_owner"] or ""
    by = m["birth_year"] or ""
    sp = m["spouse_name"] or ""
    bio = m["bio"] or ""
    print(f'  id={m["id"]:3d}  gen={m["generation"]:+d}  {nm:25s}  rel={rel:20s}  birth={str(by):6}  dead={m["deceased"]}  spouse={sp}  bio={bio}')

# Stories
stories = conn.execute('SELECT speaker_name, COUNT(*) as cnt FROM stories WHERE tenant_id = 2 GROUP BY speaker_name').fetchall()
print(f'\n=== STORIES BY SPEAKER ===')
for s in stories:
    spk = s["speaker_name"] or "(none)"
    print(f'  {spk:20s}  {s["cnt"]} stories')

# Existing chapters
drafts = conn.execute('SELECT chapter_number, title, bucket, life_phase FROM chapter_drafts WHERE tenant_id = 2 ORDER BY chapter_number').fetchall()
print(f'\n=== CHAPTER DRAFTS ({len(drafts)}) ===')
for d in drafts:
    print(f'  Ch {d["chapter_number"]}: {d["title"]} ({d["bucket"]}/{d["life_phase"]})')

# Memory stats
total_mems = conn.execute('SELECT COUNT(*) FROM memories WHERE tenant_id = 2').fetchone()[0]
with_year = conn.execute('SELECT COUNT(*) FROM memories WHERE tenant_id = 2 AND estimated_year IS NOT NULL').fetchone()[0]
print(f'\n=== MEMORIES: {total_mems} total, {with_year} with estimated_year ===')

# Life phases
phases = conn.execute('SELECT life_phase, bucket, COUNT(*) as cnt FROM memories WHERE tenant_id = 2 GROUP BY life_phase, bucket ORDER BY bucket, life_phase').fetchall()
print('\n=== MEMORIES BY BUCKET/PHASE ===')
for p in phases:
    print(f'  {p["bucket"]:30s}  {p["life_phase"]:15s}  {p["cnt"]}')

# Year tags already extracted
tags = conn.execute("SELECT tag_value, COUNT(*) as cnt FROM story_tags WHERE tenant_id = 2 AND tag_type = 'year' GROUP BY tag_value ORDER BY tag_value").fetchall()
print('\n=== YEAR TAGS ===')
for t in tags:
    print(f'  {t["tag_value"]}  ({t["cnt"]} stories)')

conn.close()
