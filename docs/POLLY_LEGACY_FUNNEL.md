# Polly Legacy Funnel — System Blueprint

> The whole app is a funnel for storytelling. Every surface where a human says
> something real becomes raw material; Polly + GPT catch the meaningful stuff,
> file it into Jungian buckets, and the legacy book writes itself.
>
> *"If Chatter becomes a complaining ground, the book is about complaining too."*
> That's why the **story-value gate** and the **per-item book toggle** exist.

## Core rule

**Every source normalizes into ONE table — `memories`. The book only ever reads `memories`.**

```
 SOURCES (raw)                 NORMALIZE                  DIGEST                OUTPUT
┌──────────────────┐
│ Legacy stories   │──┐                              ┌──────────────┐
│ Photos + convos  │──┤   story-value score (gate)   │  memories    │   book_builder    ┌─────────┐
│ Chatter (+Polly) │──┼──▶ + GPT bucket-tagging   ──▶│  source=...  │──▶ chunked by   ──▶│  BOOK   │
│ Wall (friends)   │──┤   one item at a time         │ include_in_  │   chapter         │ chapters│
│ Q&A / interviews │──┘                              │ book, is_quote│                   └─────────┘
└──────────────────┘                                 └──────────────┘                   story_narratives
                                                                                          (cached prose)
```

- `stories` = raw transcript/audio archive (unchanged).
- `memories` = distilled, bucketed unit GPT reads. **The funnel's collection point.**
- `narrative_log` = query log (bookkeeping). NOT a digestion point.
- `story_narratives` = cache of GPT prose for replay/read-aloud. Downstream.
- `chapter_drafts` = assembled chapters (book_builder output).

## Decisions (locked)

| Decision | Choice |
|---|---|
| Capture model | **Hybrid** — GPT scores story-value on post; high → auto-capture, low → stays chatter only, Polly button captures on demand |
| Book default | **Everything in (opt-out)** — any *captured* memory is book-bound until the 📖 toggle removes it |
| Polly button | **Conversational interjection + capture in one pass** — Polly chimes into the thread in-persona AND files the memory underneath |

## Schema additions (memories table)

Added in `database.py` mem_migrations (additive, PRAGMA-guarded):

- `source TEXT DEFAULT 'story'` — `story | photo | chatter | wall | question | interview`
- `source_ref INTEGER` — id of the originating post/photo/wall item (for toggle + dedupe)
- `include_in_book INTEGER DEFAULT 1` — the 📖 opt-out flag
- `is_quote INTEGER DEFAULT 0` — short attributed pull-quote (family quotes in the book)
- `story_value REAL` — GPT story-value score 0–1 (transparency + sorting)

## Chunking discipline (the lesson from writing real books)

GPT NEVER sees the whole life at once. Two chunk sizes:

1. **Capture — 1 item.** The moment a thread/photo/story happens, GPT digests *just
   that one item* into 1+ memory rows. Cheap, incremental, runs all year.
2. **Book assembly — 1 chapter (~one bucket, 5–15 memories).** `book_builder`
   groups by `bucket` + `life_phase`; GPT writes one chapter per call. Never all
   memories in one prompt.

## The Polly button (Chatter)

One tap → one GPT pass that returns BOTH:
- **Interjection** — Polly's warm, curious, in-persona "2 cents" posted into the
  thread as a comment (she's a member of the conversation, not a popup).
- **Capture** — story-value score + bucket classification → `memories` row
  (`source='chatter'`, `source_ref=post/thread id`). Optional 1–3 follow-up
  questions surfaced as a Polly card.

Polly persona: curious, warm, thoughtful, respectful, insightful. Never intrusive.
Only speaks when the button is pressed (or passive story-trigger nudge is enabled).

## Per-surface include toggle (QR-code style)

- **Per-source default** (Settings switch): include Chatter / Wall / Photos in book.
- **Per-item override** (📖 toggle on any memory/post/photo): keep or drop from book.
  Mirrors the existing `photos.in_book` toggle pattern (`web.py` ~3538).

## Build phases

0. **Foundation** *(in progress)* — schema columns + `memory_capture.py`
   (story-value scorer + universal `capture_memory(source, ref, text, speaker)` +
   Polly-persona interjection helper). Reuses existing GPT classify in `web.py`.
1. **Chatter Polly button** — interjection + capture end-to-end; the feel-it demo.
2. **Book toggle** — `include_in_book` UI + per-source settings.
3. **Photos → stories + quotes** — `vision.py` reads photo + comments → narrative
   memory + attributed pull-quotes (`is_quote`).
4. **Wall capture** — friend wall items funnel in.
5. **Email "connect with me" invite** — grow the network (Polly-internal, NOT wired
   to BSA; borrows the pattern only).

## Hard boundaries

- **Do NOT intertwine with BSA** (`bsa-coach-platform`, WorkoutTracker). Different
  stack (Postgres/JWT vs SQLite/sessions). Borrow the email-invite *pattern* only.
- AI provider = **OpenAI** (`OPENAI_API_KEY`), consistent with rest of Polly.
- Live deploy = build + scp to EC2 (`ec2-user@3.19.135.182:/opt/polly-connect`)
  then push to `master`. Never `reset --hard` (live asset drift). polly.db gitignored.
</content>
