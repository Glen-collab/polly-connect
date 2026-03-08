# Polly Connect - Complete Feature Reference

**Version:** March 2026
**Live URL:** https://polly-connect.com
**Status:** Deployed and operational

---

## What Is Polly Connect?

Polly Connect is a voice-powered companion device and cloud platform designed for elderly care and family legacy preservation. A small ESP32-S3 device sits in the home and listens for voice commands. It tells jokes, reads bible verses, asks guided questions, records family stories, manages medication reminders, and over time builds a printed family legacy book from the conversations it captures.

The system has three audiences:
- **The elder** — talks to Polly like a companion, shares stories, hears jokes and scripture
- **The caretaker** — manages medications, reviews transcripts, monitors engagement via web portal
- **The family** — views stories, photos, and book progress through a read-only family portal

---

## Hardware

### Breadboard Prototype (ESP32-S3)
- **Board:** ESP32-S3-WROOM-1 with 8MB PSRAM and 16MB flash
- **Microphone:** INMP441 I2S MEMS mic (GPIO 4/5/6)
- **Speaker:** MAX98357A I2S amplifier (GPIO 10/11/12)
- **Status LED:** GPIO 48 (solid on during recording, blinks on wake)
- **Story Button:** GPIO 0 (BOOT button, doubles as story record toggle during runtime)
- **Power:** USB-C, 5V via AMS1117-3.3 regulator
- **Connectivity:** WiFi (2.4GHz), streams audio to cloud server via WebSocket

### Waveshare ESP32-S3 AI Smart Speaker
- **Board:** Waveshare ESP32-S3-AUDIO with ES7210 (4-ch ADC), ES8311 (DAC), TCA9555 (I/O expander)
- **I2C bus:** SDA=GPIO11, SCL=GPIO10 (shared for ES7210, ES8311, TCA9555)
- **I2S bus:** MCLK=GPIO12, BCLK=GPIO13, WS=GPIO14, DOUT=GPIO16, DIN=GPIO15
- **Buttons:** K1/+ (story record), K2/SET, K3, BOOT, Reset — via TCA9555 I/O expander
- **Story Button:** K1/+ (TCA9555 Port 1 bit 1) — press to start/stop story recording
- **WiFi Provisioning:** AP captive portal ("Polly-Setup"), DNS redirect, force-provision via BOOT hold

### Custom PCB (In Progress)
- KiCad 9.0.7 schematic verified and complete
- 70mm x 50mm 2-layer board
- All components on 5-pin breakout headers for mic and amp
- Boot button (GPIO0) and Reset button (EN)
- USB-C for power and firmware flashing

---

## Voice Features

### Wake Word Detection
- Server-side VAD (Voice Activity Detection) with RMS threshold monitoring
- ESP32 streams continuous audio to server; server detects speech onset
- Pre-roll buffer captures 1.5 seconds before trigger so nothing is missed
- 3-second cooldown after responses to prevent speaker feedback loops

### Speech-to-Text
- **Engine:** Google Cloud STT (free tier: 60 minutes/month)
- Real-time transcription of voice commands and story answers
- Segment-based transcription during long recordings (3s silence gaps)

### Text-to-Speech
- **Engine:** AWS Polly (female voice)
- Audio sent back to ESP32 as chunked base64 over WebSocket
- Plays through MAX98357A speaker

### Conversation Modes
| Mode | Trigger | Behavior |
|------|---------|----------|
| COMMAND | Wake word | Normal mode — listens for commands, 2s silence timeout |
| STORY_PROMPT | "Ask me a question" | Polly asks a guided question, waits for answer (8s timeout) |
| STORY_LISTEN | "Record my story" | Free-form storytelling, Polly just listens (8s timeout) |
| FOLLOWUP_WAIT | After story answer | ECHO-BRIDGE-INVITE follow-up question (8s timeout) |
| STORY_RECORD | Button press | Full WAV recording with live transcription (15s timeout, 30min max) |
| AWAITING_RELATIONSHIP | New speaker intro | Asks "How do you know [owner]?" (8s timeout) |

### Voice Commands
- "Tell me a joke" — random joke from 1,040-joke database
- "Tell me a kid joke" / "Tell me a fart joke" — 100 silly kid jokes
- "Read me a bible verse" / "Verse about hope" — daily verse from 336-verse collection
- "What's the weather" / "Do I need an umbrella?" — real local weather + almanac fun fact
- "Ask me a family question" — guided family question (story mode)
- "Tell me a story" / "Record my story" — free-form story mode
- "How many stories do I have?" — story progress
- "My keys are on the counter" / "Where are my keys?" — item memory
- "What are my medications?" / "I took my medicine" — medication info + logging
- "Tell Dad I'm going to the store" — leave a message
- "Dad is going to work" / "I'm going for a walk" — status update
- "Any messages?" — check message board
- "Where is Dad?" — person location query
- "Dad is home" — clear person's messages
- "Clear the board" — clear all messages
- "Who is Mia?" — family tree lookup
- "What time is it?" / "What day is it?" — time and date
- "Be quiet" / "Hush" / "Shut up" — silence squawking
- "My name is [name]" — speaker introduction and identity tracking
- "Help" / "What can you do?" — capabilities overview
- K1/+ button press — start/stop WAV story recording (up to 30 minutes)

---

## Story Collection System

### How Stories Are Captured

**Voice-triggered (always available):**
1. User says "ask me a question" or "record my story"
2. Polly enters conversational mode (no wake word needed between exchanges)
3. User speaks; audio is transcribed in real time
4. Transcript saved to database

**Button-triggered WAV recording (GPIO0):**
1. User or caretaker presses the story button
2. LED turns solid on; Polly announces "Recording started"
3. ALL audio is captured as a WAV file while also transcribing in segments
4. Press button again to stop (or auto-stops at 30 minutes)
5. WAV file saved to server + full transcript saved to database
6. Original voice recording available for playback on web portal

### ECHO-BRIDGE-INVITE Follow-Up Engine
After each story answer, Polly generates a natural follow-up using behavioral psychology:

- **ECHO** — Reflects back a keyword from what the person said ("The kitchen table...")
- **BRIDGE** — Connects emotionally ("That sounds like it meant something special.")
- **INVITE** — Asks a follow-up question ("What did it smell like when she was cooking?")

Follow-ups are template-based (always free) with optional AI enhancement when OpenAI API key is configured. Up to 3 follow-ups per question, then a warm closing.

### Memory Extraction
Every story answer is automatically analyzed and tagged:
- **People mentioned** (family words + proper names)
- **Locations** (place keywords with context)
- **Emotions** (12 categories: joy, love, nostalgia, sadness, fear, anger, pride, gratitude, humor, courage, peace, adventure)
- **Life phase** (childhood, adolescence, young adult, adult, midlife, elder)
- **Jungian bucket** (see Legacy Book section below)

No machine learning required — pure keyword heuristics that run instantly.

---

## Legacy Book System

### The Jungian Narrative Arc (Hero's Journey)
Every memory is automatically classified into one of six narrative stages:

| Stage | What It Covers | Example |
|-------|---------------|---------|
| Ordinary World | Everyday life, family rhythms, childhood | "What did a normal day look like?" |
| Call to Adventure | Moments that changed everything | "When did you realize things were different?" |
| Crossing Threshold | Big decisions, no going back | "What was the hardest decision you made?" |
| Trials, Allies & Enemies | Hard times, who helped, who didn't | "Who stood by you when it got tough?" |
| Transformation | How you changed, what you became | "How were you different after all that?" |
| Return with Knowledge | Wisdom, lessons, legacy | "What would you tell your grandkids?" |

### Intelligent Question Selection
The Engagement Tracker monitors which narrative buckets and life phases have gaps:
- If "transformation" stories are thin, Polly asks deeper reflective questions
- If "childhood" is well-covered but "young adult" is empty, Polly steers there
- Perspective rotation after 10+ memories: revisit stories from emotion, relationship, lesson, and legacy angles

### Chapter Assembly
The Book Builder groups memories into 14 chapter templates:
- "Where It All Started" (ordinary world / childhood)
- "The Kitchen Table" (ordinary world / childhood)
- "Growing Up" (ordinary world / adolescence)
- "When Things Changed" (call to adventure / adolescence)
- "Stepping Out" (call to adventure / young adult)
- "The Decision" (crossing threshold / young adult)
- "Love and Beginnings" (crossing threshold / young adult)
- "The Hard Years" (trials / adult)
- "Who Stood By Me" (trials / adult)
- "Raising a Family" (trials / adult)
- "How I Changed" (transformation / adult)
- "Finding My Way" (transformation / midlife)
- "What I Know Now" (return with knowledge / reflection)
- "For the Grandkids" (return with knowledge / reflection)

Each chapter needs 5+ memories to be marked "ready." Large groups automatically split into parts. Chapters can always receive more memories and be regenerated.

### AI Chapter Draft Generation
When a chapter has enough memories, one click generates a full narrative draft:
- OpenAI GPT-4o weaves 5-10 memories into 7-10 paragraphs of prose
- Preserves the speaker's voice and emotional tone
- Adds gentle transitions between memories
- Opens with scene-setting, closes with reflection
- Cost: ~$0.02-0.05 per chapter, under $1 for a full book

### PDF Book Export
Print-ready 6x9 inch PDF generated on demand:
- **Trim size:** 6" x 9" (standard memoir format)
- **Margins:** gutter 0.85", outside 0.65", top/bottom 0.75" (KDP/Lulu safe for soft and hardcover)
- **Layout:** title page, copyright, optional dedication, table of contents, chapters, back matter
- **Typography:** Times Roman, justified body text, indented paragraphs
- **QR codes:** Each chapter can include a scannable code linking to the original voice recording
- **Page numbers:** Centered bottom, skipped on title/copyright
- **Compatible with:** Amazon KDP (via Book Bolt), Lulu, IngramSpark, Blurb

### Service Tiers
| Tier | Price | What's Included |
|------|-------|----------------|
| Free (with device) | $0 | Voice capture, web dashboard, transcript review, story progress |
| Legacy Book | $49-99 | AI chapters, PDF export, 1 printed softcover book |
| Premium Package | $149-249 | Editor review, custom cover, 3 hardcover copies, QR audio companion |

---

## Medication Reminder System

### Setup
- Add medications via web portal: name, dosage, times, active days
- Accepts flexible time input: "8am", "2:30 PM", "14:00"
- Day-of-week checkboxes for active days

### Voice Reminders
- Background scheduler checks medication times every minute
- At scheduled time: plays a squawk sound (random 1-of-5) + TTS announcement
- Pushed directly to ESP32 via WebSocket — no user action needed
- Tenant-aware: only sends to devices belonging to the medication's tenant
- Dedup prevents duplicate sends within the same minute

### Dashboard Alerts
- Live medication status on dashboard (polls every 60 seconds)
- Color-coded badges: OVERDUE (red), Soon (yellow), Scheduled (green), Not Today (gray)
- Countdown minutes to next dose

### Calendar Export
- Download .ics file for phone calendar import
- RRULE-based recurring events with 5-minute advance alarms
- Works with Apple Calendar, Google Calendar, Outlook

---

## Web Portal

**URL:** https://polly-connect.com/web/
**Design:** Mobile-first, Tailwind CSS, responsive
**Auth:** Cookie-based sessions, 72-hour duration

### Pages

| Page | URL | Who Can Access | Purpose |
|------|-----|---------------|---------|
| Login | /web/login | Everyone | Email + password login |
| Register | /web/register | Everyone | Create account + household |
| Family Login | /web/family | Everyone | 6-digit code + name (no password) |
| Dashboard | /web/dashboard | All logged in | Stats, recent stories, med alerts, book progress |
| Stories | /web/stories | All logged in | Story list with audio playback, edit links |
| Story Edit | /web/stories/{id}/edit | All logged in | Edit transcript and speaker name |
| Legacy Book | /web/book | All logged in | Book progress, arc coverage, chapter outline, PDF export |
| Book Chapters | /web/book/chapters | All logged in | Chapter list with status badges and memory previews |
| Chapter Detail | /web/book/chapters/{n} | All logged in | Source memories, AI draft editor, generate/regenerate |
| Book Export | /web/book/export | All logged in | Download 6x9 print-ready PDF |
| Transcriptions | /web/transcriptions | All logged in | Review/verify/correct transcripts |
| Photos | /web/photos | All logged in | Photo gallery with upload, tags, captions |
| Memory | /web/memory | All logged in | Item storage + AI photo scan |
| Medications | /web/medications | All logged in | Add/edit/delete medications |
| Med Edit | /web/medications/{id}/edit | Owner only | Edit medication details |
| Med Calendar | /web/medications/calendar | All logged in | Download .ics calendar |
| Setup | /web/setup | Owner only | Owner/caretaker names and emails |
| Settings | /web/settings | Owner only | Preferences, squawk intervals, quiet hours, snooze, family codes |
| Messages | /web/messages | All logged in | Family message board (send/delete/clear) |
| Devices | /web/devices | Owner only | Manage Polly devices + API keys |

### AI Photo Scan
- Upload a photo of a shelf, wall, drawer, etc.
- OpenAI GPT-4o Vision identifies specific items ("claw hammer" not "hammer")
- Items appear as editable cards — user can rename before saving
- Location field with autocomplete from previously-used locations
- Batch save stores all items to Polly's memory
- Cost: ~$0.005-0.01 per scan

### Family Access
- Owner generates a 6-digit family access code in Settings
- Family members log in with just their name + the code (no email/password)
- Family sessions are read-only — can view stories, photos, book progress
- Cannot edit medications, settings, or device management

---

## Multi-Tenant Architecture

- Each household is a "tenant" with isolated data
- **Tables:** tenants, accounts, web_sessions
- **tenant_id** on all 15 data tables (not shared data like bible_verses)
- Per-device API keys for ESP32 authentication
- Backward compatible: global POLLY_API_KEY falls back to tenant #1
- SQLite with WAL mode for concurrent access
- Password hashing: SHA-256 with random salt

---

## Infrastructure

### Server
- **AWS EC2** instance at 3.14.130.158
- **OS:** Amazon Linux
- **Runtime:** Python 3.11 + FastAPI + Uvicorn
- **Database:** SQLite (21 tables, WAL mode)
- **Process:** systemd service (auto-restart)

### Domain and SSL
- **Domain:** polly-connect.com (GoDaddy, auto-renews Jan 2027)
- **SSL:** Let's Encrypt via certbot (auto-renewing, expires May 2026)
- **Proxy:** Nginx reverse proxy (port 80/443 to :8000)

### Deployment
```
git push origin master
ssh into EC2
cd /opt/polly-connect && git pull origin master
sudo systemctl restart polly-connect
```

---

## Parrot Sounds & Ambient Personality

- 5 short squawks (0.6-1.8s) + 3 parakeet chatter clips (~50s each)
- Startup squawk on device connect (confirms Polly is ready)
- Post-response squawk: 50% chance after any TTS response
- Idle squawk interval: configurable (5-60 minutes, default 10)
- Chatter interval: configurable (15 min-4 hours, default 45 min)
- **Quiet Hours**: automatic bedtime/wake schedule (default 9 PM-7 AM)
- **Snooze**: temporarily quiet all sounds from web portal (30 min / 1 hr / 2 hr / 8 hr)
- **Interruptible**: "Be quiet", "Shut up", "Hush", "Shush" with sassy responses
- All sounds auto-converted to 16kHz mono, volume reduced to 30%
- All server-side — no firmware changes needed

---

## Family Message Board

- Voice status updates: "Dad is going to work" / "I'm going for a walk"
- Voice messages: "Tell Dad I'm going to the store"
- Voice queries: "Any messages?" / "Where is Dad?"
- "Dad is home" clears dad's messages from board
- Messages auto-expire after 24 hours
- Web message board at /web/messages (send/delete/clear)
- Family tree names loaded for person recognition
- Status vs. direct message readback formatting

---

## Database Schema (22 Tables)

| Table | Purpose |
|-------|---------|
| tenants | Household/account grouping |
| accounts | User login credentials |
| web_sessions | Active browser sessions |
| user_profiles | Owner preferences and settings |
| devices | ESP32 devices with API keys |
| stories | Voice transcripts and WAV recordings |
| story_tags | Tags on stories (speaker, topic) |
| memories | Structured memories (tagged with bucket, life phase, emotions) |
| memory_verifications | Audit trail for verified memories |
| chapter_drafts | AI-generated book chapter text |
| question_sessions | Which questions have been asked/answered |
| medications | Medication names, dosages, schedules |
| medication_logs | Medication reminder delivery log |
| items | Stored items (location memory) |
| photos | Uploaded photos with captions and tags |
| family_members | Known family members and relationships |
| sessions | Voice conversation sessions |
| joke_history | Which jokes have been told |
| bible_verses | 336 verses (shared, not per-tenant) |
| almanac_weather | 52-week weather forecasts (shared) |
| family_messages | Message board (from, to, message, expiry) |

---

## Data Content

| Content Type | Count | Source |
|-------------|-------|--------|
| Jokes | 1,040 | Curated JSON files |
| Family Questions | 70 | Curated, Jungian-tagged |
| General Questions | 312 | Curated JSON files |
| Bible Verses | 336 | Curated, topic-categorized |
| Almanac Forecasts | 52 | Weekly forecasts |

---

## Key Technical Files

| File | Purpose |
|------|---------|
| server/main.py | FastAPI app, service wiring, static mount |
| server/config.py | Settings, .env loading, timezone |
| server/core/database.py | 21 tables, migrations, all CRUD |
| server/core/command_processor.py | All voice intent handling |
| server/core/conversation_state.py | 6 conversation modes, timeouts |
| server/api/audio.py | WebSocket audio streaming (continuous + event-based) |
| server/api/web.py | All web portal routes |
| server/core/echo_bridge_invite.py | ECHO-BRIDGE-INVITE follow-up engine |
| server/core/narrative_arc.py | Jungian arc tracking, question guidance |
| server/core/memory_extractor.py | Auto-tagging of people, emotions, life phase |
| server/core/book_builder.py | Chapter assembly + AI draft generation |
| server/core/book_pdf.py | 6x9 PDF export with QR codes |
| server/core/story_recorder.py | WAV recording session manager |
| server/core/engagement.py | Question selection + progress tracking |
| server/core/vision.py | OpenAI GPT-4o Vision for photo scanning |
| server/core/family_identity.py | Speaker intro + relationship tracking |
| server/core/web_auth.py | Session handling, login, family access |
| server/core/medications.py | Medication scheduler + voice push |
| server/core/squawk.py | Parrot sounds, intervals, quiet hours, snooze |
| server/core/intent_parser.py | Voice command recognition (35+ intents) |
| firmware/polly-s3-wakeword/main/main.c | ESP32 firmware — breadboard (INMP441 + MAX98357A) |
| firmware/polly-waveshare-s3/main/main.c | ESP32 firmware — Waveshare (ES7210 + ES8311 + TCA9555 + K1 button) |

---

## What's Next

### Immediate (Pre-Trial)
- Flash second Waveshare device for family deployment
- Full end-to-end voice pipeline test (test_A automated suite)
- Family trial: real story capture with Grandma

### Short Term
- Install OpenAI package on EC2 for AI chapter generation
- Test print via Book Bolt / KDP
- Audio companion web page behind QR codes

### Medium Term
- KiCad PCB routing and fabrication
- Lulu API integration for automated print-on-demand
- Cover template generator with family photos
- Mobile app wrapper (PWA or native)
- Suno AI personalized music generation

### Long Term
- Multi-device household support
- Video message recording
- Integration with smart home (Home Assistant)
- Subscription model for ongoing story capture + annual book updates
