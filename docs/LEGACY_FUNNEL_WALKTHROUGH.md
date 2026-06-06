# Polly Legacy Funnel — What We Built (Owner Walkthrough)

*Started 2026-06-02, last updated 2026-06-06. Everything below is LIVE on polly-connect.com and pushed to `master`.*

---

## The big idea

**The whole app is now a funnel for storytelling, and the legacy book is the exhaust.**

Every place a person says something real — a Chatter message, a friend-Wall
conversation, a photo someone reminisces over, a recorded story — flows into one
place: your **memory buckets**. Polly + GPT catch the meaningful stuff, file it
into the right chapter of your life, and the book writes itself over time.

> Your own line on it: *"If Chatter becomes a complaining ground, the book is
> about complaining too."* That's exactly why there's a quality gate and an
> on/off switch — see below.

One rule underneath it all: **every surface feeds the same `memories` table, and
the book only ever reads from that table.**

---

## What's live right now

### 1. The Polly button in Chatter 🦜
- In any Chatter group, tap **"Ask Polly to chime in."**
- Polly reads the recent conversation, **posts her two cents right into the
  thread** — warm, curious, in-character, like a member of the family chiming in.
- Underneath, that same pass **captures the meaningful part into your book** and
  offers a few tap-to-answer follow-up questions.
- She only speaks when invited (the button) — never barges in.

### 2. Automatic capture (the quiet part)
- Every **text** message posted in Chatter is quietly scored 0–1 for "is this
  legacy-worthy?" The good ones **auto-save to your book**; the noise
  ("ugh, Mondays") just stays chatter. No button needed.
- Friend-**Wall** comments work the same way.
- This is the "hybrid" model you picked: capture the gold automatically, filter
  the junk, and the Polly button is the on-demand booster.

### 3. The friend Wall
- Same **"Ask Polly to chime in"** button. She reads the wall, leaves a comment,
  and pulls the meaningful remembrances into the book.

### 4. Photos (reworked to your spec)
- **Photos are in the book automatically**, with their QR code, placed in the
  right chapter by date. No button, nothing to trigger.
- Polly does **not** interject on the photo itself.
- Each family member can leave **their own remembrance** on a photo ("Tell me
  about this photo" — type or record). Each becomes its own memory tied to that
  photo.
- When the book is written, Polly keeps **everyone's version side by side**,
  attributed by name — she never forces one "official" account.
  *(Your marriage-photo example: brother and sister-in-law remember the day
  differently → both stand in the book, in their own words.)*

### 5. The book
- Memories are organized into ~20 chapters along a life arc (childhood →
  turning points → trials → transformation → wisdom).
- **Every captured memory is IN the book by default** (your "everything in"
  choice). On each chapter you'll see a 📖 toggle per memory — tap to drop
  anything you don't want.
- Photos and family quotes get woven in.

### 6. "Invite a friend to Polly"
- On the Chatter page: enter a name + email, and they get an invite to connect
  with you on Polly. Once they join, you can add them to your groups.
- *(Completely separate from the workout/BSA apps — borrowed the idea, not the
  code.)*

### 7. Family Tree — cleaned up
- Removed the confusing tree-**sharing** controls (the "Share My Tree With"
  checkboxes, the "view other people's trees" switcher, the request/approve
  flow). Your tree is now private to you and shows immediately.
- Your tree, "Add Family or Friends," and friend connections all stay.
- *(The underlying data was kept, so it's a one-flip revert if you ever want
  sharing back.)*

### 8. Editing & cleanup refinements (June 3–6)
- **Edit a photo's story text inline** — on the Photos page, each saved story now
  has an **Edit** button that opens the text right there (Save / Auto-Format).
  Before, you had to detour over to Stories to fix wording.
- **Edit a Story Narrative's Topic** — fix a misspelled topic or name right in the
  narrative editor (e.g. "matt levinsky" → "Matt Lubinski").
- **Stories: QR + audio follow the in-book toggle** — flip a story's QR "out of
  the book" and its QR code *and* audio player hide in the Stories view; toggle it
  back in and they reappear (live, no reload). Toggle button always stays visible.

### 9. The physical Polly device is LIVE 🦜 (June 3–6)
- Paul's v2 PCB is fully working as a **standalone voice device** — no Home
  Assistant, talks straight to your Polly Connect server.
- **WiFi:** auto-connects to saved networks; for a new place it starts a
  `Polly-Setup` hotspot — connect your phone, go to `192.168.4.1`, enter WiFi
  (2.4 GHz only). It remembers networks.
- **Use it:** say **"Hey Polly"** (normal, even tone) + your question — she answers
  out the speaker. The **BOOT button** = "record my story" (records a full memory
  until pressed again).
- Fixed a server bug that was dropping the device connection every ~30s
  (global-key devices crashed on the keepalive ping). Now rock-steady.
- Speaker plugs into **CN1** (JST PH 2.0 mm 2-pin); the amp self-enables, no
  firmware change needed.

---

## How capture decides — at a glance

| Surface | Auto-captured? | Needs a tap? |
|---|---|---|
| Chatter text message | ✅ if it scores high | No |
| Chatter photo/voice post | ❌ | — |
| Wall comment | ✅ if it scores high | No |
| Photo (the picture itself) | ✅ always, with QR | No |
| A person's remembrance on a photo | ✅ | They record/type it |
| "Ask Polly to chime in" (Chatter/Wall) | ✅ always | Tap |

**The bar:** right now ~0.6 out of 1. Leans toward capturing (matches your
"everything in, toggle out" choice). Easy to raise (gold only) or lower
(capture more) anytime.

---

## How GPT digests it (the part you cared about)

You said it from writing your own books: **never hand GPT the whole life at
once.** It doesn't.

- **At capture:** one message/photo/story at a time → one memory. Cheap,
  constant, all year long.
- **At book time:** GPT writes **one chapter from one bucket** (~5–15 memories),
  then the next. Never all of it in one prompt.

So the "Narratives" question you asked — the answer is: everything lands in the
**`memories`** table (your buckets), and the book reads chunk-by-chunk from
there. The other "narrative" tables are just a query log and a cache of finished
prose for read-aloud — not where digestion happens.

---

## Your decisions (locked)

- **Capture model:** Hybrid — score everything, auto-save the meaningful, Polly
  button on demand.
- **Book default:** Everything in, toggle out (opt-out).
- **Polly on Chatter/Wall:** chimes in *and* captures, in one pass.
- **Polly on Photos:** no interjection; weave the differing remembrances instead.
- **Chronology:** arc placement matters, exact dates don't. A little jumping
  within the right chapter is fine — the journey is what readers feel.

---

## Test-drive result (2026-06-02)

You have **59 real memories** in your buckets already. We dropped a "college
football + parties" remembrance through the live pipeline:

- **Score 0.80** → high, auto-captured
- **Bucket:** ordinary_world · **Phase:** young_adult
- Read as the *carefree backdrop* of the college years (not a turning point) —
  it pools just before your 2004 "call to adventure" (first bodybuilding show).

From your real data, GPT produced a clean opening paragraph, a 3-chapter outline
("Where It All Started" → "The Weight Room" → "Stepping Out"), and a closing
paragraph — every beat traceable to an actual memory, no invention. You approved
the shape.

---

## Optional follow-ups (not built yet — your call)

1. **Comments-about-a-photo clustering** — if people discuss a photo over in
   Chatter/Wall (instead of on the photo itself), pull those comments to sit
   next to that photo in the book. *(Per-photo remembrances already do this; this
   is for the scattered-conversation case.)*
2. **"Excluded memories" view** — a place to see and re-include anything you've
   toggled out of the book.
3. **Per-source default switches** in Settings (e.g. "Wall off by default").
4. **Tune the capture bar** up or down once you've felt it with real use.

**Device-side polish (optional, not built):**
5. **WiFi power-save off** (`esp_wifi_set_ps(WIFI_PS_NONE)`) — trims the occasional
   reconnect (currently drops ~every 8–19 min, auto-heals in 5s; harmless).
6. **Bigger response-audio buffer** — long replies (30s+) overflow the device's
   960 KB buffer ("Response audio buffer full!"); bump it or cap reply length.
7. **Photo in/out toggle to match QR** — mirror the QR+audio show/hide for the
   photo's own in-book toggle if wanted.

---

## Technical notes (for reference)

- **New module:** `server/core/memory_capture.py` (scorer + universal capture +
  Polly persona).
- **Schema:** `memories` gained `source`, `source_ref`, `include_in_book`,
  `is_quote`, `story_value` (additive migration, applied to live DB).
- **Blueprint:** `docs/POLLY_LEGACY_FUNNEL.md` (architecture).
- **Provider:** OpenAI (gpt-4o-mini for text, gpt-4o for vision).
- **Commits on `master` (this run):** Legacy Funnel build → family-tree cleanup →
  photo rework → WebSocket `db_device_id` server fix → editable narrative Topic →
  inline photo-story edit → Stories QR+audio show/hide. All deployed to
  `ec2-user@3.19.135.182:/opt/polly-connect`, `polly-connect.service` healthy.
- **Device firmware:** `firmware/polly-s3-wakeword` (ESP-IDF) runs Paul's v2
  board; `firmware/polly-v2-bringup` is the hardware bring-up test. Pin map +
  build notes in the project memory.
- **Provider:** OpenAI (gpt-4o-mini for text, gpt-4o for vision).
- **Boundary kept:** zero entanglement with the BSA / WorkoutTracker stack.
