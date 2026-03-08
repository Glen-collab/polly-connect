# Polly Connect - Full Feature Map

## Core Identity
A parrot companion device for elderly users. Revolves around **one primary user** and their story. Caretakers/family can interact too (Polly asks their name). Web/mobile app for editing and management.

**The R2-D2 of devices, disguised as a parrot.**

---

## Feature 1: Legacy Book Writer (Story Mode)

### Story Mode
- User talks freely to Polly, WAV is recorded and saved
- Transcribed via Amazon Transcribe (or Whisper)
- Transcriptions are themed, organized by chapter/topic
- Compiled over time into a legacy family book

### Question Mode
- 5 guided questions per week + 15 follow-up questions = 20 questions/week
- 1,000+ total questions across a year
- Questions organized by themes: childhood, career, marriage, regrets, lessons, faith, etc.
- Answers are transcribed and stored (text only, no WAV)
- Both Story Mode and Question Mode feed into the same book

### Subscription Tiers
- **Basic**: 15 min/week story mode
- **Premium**: 30+ min/week story mode
- **Overage**: If user goes over, prompt to keep recording at premium upsell price

---

## Feature 2: WAV Button (Story Capture)

- Physical button on the ESP32 device (K1/+ on Waveshare, BOOT on breadboard)
- Caretaker or family member presses it to capture special family moments
- User can press it themselves to just talk and save for the book
- Press once to start recording, press again to stop (or auto-stops at 30 minutes)
- LED turns solid during recording; Polly announces "Recording started" / "Recording stopped"
- Saved WAV is transcribed and feeds into Legacy Book alongside Story Mode and Questions
- Think of it as a "save this moment" button

---

## Feature 3: Memory Storage ("Where's the hammer?")

### Voice Mode (Working)
- Store items + locations by voice: "The hammer is in the garage"
- Retrieve by voice: "Where's the hammer?" → "The hammer is in the garage"

### Camera Mode (Web/Mobile App)
- Take a photo of a wall, shelf, drawer, toolbox, etc.
- AI (ChatGPT Vision) identifies all visible items in a list
- User assigns a location: "put on west wall", "in right kitchen drawer"
- Bulk-imports all identified items into memory storage
- Makes retrieval easy later when user asks by voice

---

## Feature 4: Medication Reminders

### Scheduling
- Add via mobile app or by voice: "Grandma takes X pill at Y time"
- Add/remove/edit schedules easily on phone

### Alerts
- Polly squawks at the scheduled time
- Speaks: "Reminder! Take [X pill], [X amount] now."
- Follow-up check later: "Did you take your pills?"

### Compliance Tracking
- Documents whether pills were taken (yes/no + timestamp)
- Caretaker can view history on web/mobile app
- Huge value for remote family members monitoring care

---

## Feature 5: Daily Bible Verse

- 365+ verses, one per day
- Organized by ~50 topics:
  - Resilience, strength, old age, marriage, blessings, forgiveness, gratitude,
    hope, patience, wisdom, courage, comfort, peace, joy, faith, love,
    family, friendship, loss, healing, purpose, prayer, trust, mercy,
    kindness, humility, perseverance, rest, provision, protection,
    guidance, renewal, praise, thankfulness, contentment, grace,
    redemption, faithfulness, generosity, compassion, truth,
    righteousness, eternal life, salvation, obedience, service,
    community, stewardship, creation, sovereignty
- User or caretaker picks topic focus for the week (via voice or app)
- Daily verse + brief reflection/message about the verse
- Polly reads it each morning automatically or on command

---

## Feature 6: Weather (Real + Almanac)

- Trigger: "What's the weather?" / "Do I need an umbrella?"
- **Real weather** from Weather.gov API (free, no key needed)
- Auto-detects location from device IP via geolocation
- Current conditions + today's forecast + tomorrow + Farmer's Almanac fun fact
- Falls back to pre-loaded almanac forecasts if API fails
- 2-hour cache per IP to minimize API calls

---

## Feature 7: Personalized Music (Suno AI)

- Takes legacy questions + answers from the user's story
- Generates personalized songs from their life experiences
- User picks genre preference (country, gospel, folk, jazz, etc.)
- Frequency: once a month or based on subscription tier
- Example: A country song about grandma growing up on the farm
- Delivered via app and/or played through the device
- Emotional keepsake tied directly to their legacy book content

---

## Feature 8: Jokes & Personality

- 1,040+ jokes + 100 kid jokes (fart, poop, dinosaur, unicorn)
- Casual conversation triggers: "Tell me a joke", "Make me laugh", "Cheer me up"
- Kid jokes: "Tell me a kid joke", "Tell me a fart joke", "Tell me a dinosaur joke"
- SSML punchline timing with 2-second dramatic pause
- Seasonal rotation keeps it fresh
- This is what makes Polly feel alive — not just a tool, but a companion

---

## Feature 8b: Parrot Sounds & Ambient Personality

- 5 short squawks (0.6-1.8s) + 3 parakeet chatter clips (~50s each)
- **Startup squawk**: plays when device connects (confirms Polly is ready)
- **Post-response squawk**: 50% chance after any TTS response
- **Idle squawk**: random every 5-60 minutes (configurable)
- **Chatter**: random every 15 min-4 hours (configurable)
- **Quiet Hours**: Polly goes to sleep at bedtime, wakes up in the morning (configurable)
- **Snooze**: temporarily quiet all sounds from web portal (30 min, 1 hr, 2 hr, 8 hr)
- **Interruptible**: "Be quiet", "Shut up", "Hush", "Shush" with sassy responses
- All sounds server-side — no firmware changes needed

---

## Feature 9: Help & Navigation

- Voice-driven commands:
  - "What can you do?" / "Help" → capabilities overview
  - "Repeat that" / "Say that again" → replays last response
  - "Skip" / "Next question" / "I don't know" → moves on
  - "Stop" / "I'm done" / "That's enough" → ends current interaction
  - "Be quiet" / "Hush" → silences Polly's squawking
  - "What time is it?" → current time
  - "What day is it?" → current date
  - "Thank you" → polite response
  - "Who is [name]?" → family tree lookup
  - "Goodbye" / "Good night" → farewell
- Discoverable and forgiving — designed for elderly users

---

## Feature 9b: Family Message Board

- **Status updates**: "Dad is going to work" / "I'm going for a walk"
- **Direct messages**: "Tell Dad I'm going to the store"
- **Check messages**: "Any messages?" / "Read my messages"
- **Person queries**: "Where is Dad?"
- **Clear by person**: "Dad is home" (clears dad's messages)
- **Clear all**: "Clear the board"
- Messages auto-expire after 24 hours
- Web message board at /web/messages (send/delete/clear)
- Family tree names loaded for person recognition

---

## Feature 10: Web & Mobile App (Caretaker Portal)

### For Caretakers / Family
- Edit transcriptions (fix misspelled names, pronunciation errors, clean up flow)
- Manage medication schedules (add/remove/edit)
- View medication compliance history
- Choose Bible verse topics for the week
- View and export legacy book progress

### Camera → Memory Storage
- Take photo of wall/shelf/drawer
- AI identifies items → assign locations → bulk import to memory

### For the Primary User (simplified view)
- Listen to their stories
- View their book progress
- Play their personalized songs

---

## Multi-User Model

- **Device = one primary user** (the elder whose story it is)
- Others can contribute stories — Polly asks for their name
- All contributions tagged by speaker, feed into the legacy book
- Caretakers manage everything via the app
- Multiple family members can have app access

---

## Subscription Tiers (Proposed)

| Feature | Basic ($20/mo) | Premium ($29/mo) | Notes |
|---|---|---|---|
| Memory Storage | Unlimited | Unlimited | Core feature |
| Question Mode | 5 questions/week | 20 questions/week | + follow-ups |
| Story Mode | 15 min/week | 30+ min/week | WAV saved |
| WAV Button | Yes | Yes | |
| Medication Reminders | 3 reminders | Unlimited | |
| Bible Verse | Daily | Daily + topic choice | |
| Farmer's Almanac | Weekly | Weekly | |
| Jokes | Yes | Yes | |
| Personalized Song | — | 1/month (Suno) | Premium perk |
| Web/Mobile App | View only | Full edit access | |
| Legacy Book Export | Annual | Quarterly + on-demand | |

---

## Tech Stack (Current → Target)

### Deployed Stack (Live at polly-connect.com)
- **Hardware:** ESP32-S3 (breadboard + Waveshare ESP32-S3-AUDIO)
- **Server:** AWS EC2 + Python 3.11 + FastAPI + Uvicorn
- **STT:** Google Cloud STT (free tier)
- **TTS:** AWS Polly (female voice, SSML support)
- **Database:** SQLite (22 tables, WAL mode)
- **AI:** OpenAI GPT-4o (Vision photo scan, chapter drafts), GPT-3.5-turbo (follow-ups)
- **Weather:** Weather.gov API (free) + IP geolocation
- **SSL:** Let's Encrypt via certbot + Nginx reverse proxy
- **Domain:** polly-connect.com (GoDaddy)
- **Wake word:** Server-side VAD (RMS threshold detection)
- **WiFi Provisioning:** AP captive portal ("Polly-Setup") with DNS redirect

---

## Architecture Overview

```
[ ESP32 Parrot Device ]
        |
        |  audio / wake word / button
        v
[ Brain API — AWS Cloud ]
        |
        ├── Amazon Transcribe (speech → text)
        ├── Amazon Polly (text → speech)
        ├── OpenAI API (reasoning, writing, vision)
        ├── Suno API (music generation)
        |
        ├── S3 (WAV, transcripts, books, songs)
        ├── DynamoDB (memory, Q&A, meds, profiles)
        |
        v
[ Web / Mobile App ]
        |
        ├── Caretaker portal (edit, manage, view)
        └── Camera → AI item recognition → memory
```
