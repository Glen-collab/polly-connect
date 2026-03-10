# Test Suite B — Prayer & Story Intent Coverage

**Date:** 2026-03-10
**Result:** 270 tests passed, 0 failed
**Combined (A + B):** 453 tests passed, 0 failed

---

## What Test B Covers

Test B systematically tests the two newest feature sets — **Prayer** (Phase 27) and **Stories** (Phases 0-5, 23) — covering every voice phrase, theme route, edge case, and cross-intent guard.

### Prayer Tests (175 cases)

| Category | Tests | What's Covered |
|----------|-------|----------------|
| Basic phrases | 19 | Every way to say "pray" — direct, polite, casual |
| Time-based themes | 6 | Bedtime, goodnight, morning, evening → correct theme |
| Emotional triggers | 28 | Natural speech ("I'm worried", "I miss her") → correct theme |
| Theme keywords | 26 | "Pray for strength/hope/peace..." → themed prayer, NOT person name |
| Keyword NOT person | 28 | All 28 theme words confirmed as NOT extracted as pray_for |
| Pray for person | 16 | Name extraction: "pray for Ryan", "prayer for Glen", "pray over Ryan" |
| Generic not extracted | 5 | "pray for me/us/family/kids" → pray_for stays None |
| Family-specific | 6 | Family prayer phrases → family theme |
| Healing contexts | 2 | Health/healing triggers |
| Edge cases | 11 | Cross-intent guards, unknown names, skip list coverage |
| Natural speech | 9 | Realistic STT transcriptions with "polly" prefix |
| Regressions | 4 | All prayer bugs from bugs.md |

### Story Tests (95 cases)

| Category | Tests | What's Covered |
|----------|-------|----------------|
| Hear stories | 26 | "tell me a story", "read me a story", "play my stories", "what did grandma say" |
| Query extraction | 4 | "tell me about grandma" → query="grandma" |
| Tell/record story | 16 | "let me tell you about...", "record my story", "story time" |
| Family questions | 14 | "interview me", "ask me about my life", "give me a question" |
| Story progress | 11 | "how many stories", "how's my book", "book progress" |
| Introductions | 5 | "This is Sarah", "My name is Joe" + relationship extraction |
| Cross-intent guards | 10 | Story vs prayer, story vs messages, story vs bible |
| Priority order | 5 | Intent priority verified: stories > jokes > messages > bible > prayer > items |
| Natural speech (hear) | 6 | "polly tell me a story", "can you read a story for me" |
| Natural speech (record) | 7 | "polly let me tell you about...", "hey polly story time" |
| Regressions | 5 | "what did i miss" → messages, "say a prayer for ryan" extraction |

---

## Bugs Found & Fixed During Test B Creation

### 1. Contraction normalization mangling words (NEW)
- **Symptom:** "give me strength" → unknown, "give me a question" → unknown
- **Root cause:** `"ive " → "i've "` was plain `.replace()` — matched inside "g**ive** me" → "gi've me"
- **Fix:** Changed `im`/`ive` contractions to use `re.sub(r'\b...')` word boundaries
- **File:** `server/core/intent_parser.py`
- **Affected phrases:** "give me strength", "give me a question", "give me a joke", "give me a verse", any phrase with "give"

### 2. "bless" not in gratitude theme keywords
- **Symptom:** "bless this day" → prayer with no theme (expected gratitude)
- **Fix:** Added "bless" to gratitude theme word list
- **File:** `server/core/intent_parser.py`

### 3. "happiness" not in joy theme keywords
- **Symptom:** "pray for happiness" → prayer with no theme (expected joy)
- **Fix:** Added "happiness" to joy theme word list
- **File:** `server/core/intent_parser.py`

### 4. "read me one of my stories" not recognized
- **Symptom:** → unknown (phrase not in hear_stories list)
- **Fix:** Added to `_hear_stories_phrases`
- **File:** `server/core/intent_parser.py`

### 5. Test A: "tell me a story" was in tell_story test
- **Symptom:** "tell me a story" correctly routes to hear_stories (user wants to HEAR a story), but test_A expected tell_story
- **Fix:** Moved to hear_stories test, added explicit test documenting this behavior

---

## Prayer Intent — Complete Voice Phrase Reference

### Direct Requests
```
say a prayer          pray for me           pray with me
let's pray            let us pray           can you pray
i need a prayer       prayer                pray
say a prayer for me   will you pray         i want to pray
help me pray          lead me in prayer     lead a prayer
can we pray           would you pray        pray for us
pray over me
```

### Time-Based (auto-themed)
```
bedtime prayer → rest        goodnight prayer → rest
nighttime prayer → rest      evening prayer → rest
morning prayer → strength    start the day with prayer → strength
```

### Emotional Triggers (auto-themed)
```
i'm worried → anxiety        i'm scared → anxiety
i miss him/her → grief       i feel alone → loneliness
i'm having a hard day → strength    i need some hope → hope
i need peace → peace         i'm thankful → gratitude
praise god → gratitude       bless this day → gratitude
give me strength → strength  i'm struggling → strength
```

### Theme Keywords (NOT treated as person names)
```
pray for strength/courage/resilience/perseverance → strength
pray for hope → hope
pray for peace/comfort/grace/mercy/calm → peace
pray for faith/wisdom/guidance → faith
pray for healing/health → healing
pray for forgiveness → forgiveness
pray for blessings/glory → gratitude
pray for joy/happiness → joy
pray for family/kids/grandchildren → family
```

### Pray For Person
```
pray for [name]              prayer for [name]
say a prayer for [name]      pray over [name]
pray for [name] please
```

---

## Story Intent — Complete Voice Phrase Reference

### Hear/Play Stories (hear_stories)
```
tell me a story              read me a story
play a story                 share a story
narrate a story              story reading
play my stories              read my stories
tell me my story             read me one of my stories
tell me about [topic]        any stories about [topic]
what did grandma say         what has she said
do you have any stories      play back
```

### Record a Story (tell_story)
```
let me tell you about...     i remember when...
i want to tell you...        let me share...
i have a story               story time
record my story              take my story
i want to share...           i have something to share
let me tell you something    can i tell you something
i got a story                i have a memory to share
```

### Family Questions (family_question)
```
ask me about my family       family question
ask me a family question     family story
ask me about my life         interview me
give me a question           ask me about my past
ask me about growing up
```

### Story Progress (story_progress)
```
how many stories             my progress
story progress               how's my book
book progress                how far along are we
how many have we done
```
