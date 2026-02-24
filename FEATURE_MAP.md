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

- Physical illuminated button on the ESP32 device
- Caretaker or family member presses it to capture special family moments
- User can press it themselves to just talk and save for the book
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

## Feature 6: Farmer's Almanac Weather

- Trigger: "What's the weather this week?"
- Responds with Farmer's Almanac style prediction (not a live weather API)
- Pre-loaded forecasts by week for a full year ahead
- Fits the old-school, comforting, conversational vibe
- Can be updated annually with new almanac data

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

- 460+ jokes, organized by season/week
- Casual conversation triggers: "Tell me a joke", "Make me laugh", "Cheer me up"
- Seasonal rotation keeps it fresh
- This is what makes Polly feel alive — not just a tool, but a companion

---

## Feature 9: Help & Navigation

- Voice-driven commands:
  - "What can you do?" → capabilities overview
  - "Repeat that" → replays last response
  - "Skip" / "Next question" → moves on
  - "Stop" / "Be quiet" → ends current interaction
  - "Help" → guidance on what to say
- Discoverable and forgiving — designed for elderly users

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

### Current (Local)
- ESP32-S3 (mic, speaker, LED, button)
- Python FastAPI server on local machine
- Whisper for speech-to-text
- pyttsx3 for TTS
- SQLite database
- Wake word: custom ONNX model ("Hey Polly")

### Target (Cloud — AWS Free Tier Start)
- ESP32-S3 → connects to cloud endpoint
- EC2 (t2.micro free tier) → FastAPI brain server
- Amazon Transcribe → speech-to-text
- Amazon Polly → TTS (neural voice)
- S3 → WAV files, transcripts, book chapters, songs
- DynamoDB → structured data (Q&A, memory, meds, profiles)
- OpenAI API → summaries, themes, book writing, follow-up questions
- Suno API → personalized music generation
- ChatGPT Vision → camera item recognition

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
