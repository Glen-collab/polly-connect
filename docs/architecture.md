# Polly Connect Architecture

## Overview

Polly Connect is a voice assistant system with a split architecture:

- **ESP32 Device** = Ears + Mouth (audio I/O, wake word)
- **Cloud Server** = Brain (transcription, intent parsing, TTS)

```
┌─────────────────┐         ┌─────────────────────────────────┐
│   ESP32 Device  │         │         Cloud Server            │
│                 │         │                                 │
│  ┌───────────┐  │         │  ┌─────────┐  ┌──────────────┐ │
│  │ INMP441   │  │  WiFi   │  │ Whisper │  │ Intent       │ │
│  │ Mic       │──┼────────►│  │ STT     │─►│ Parser       │ │
│  └───────────┘  │ WebSocket│ └─────────┘  └──────┬───────┘ │
│                 │         │                      │         │
│  ┌───────────┐  │         │  ┌─────────┐  ┌──────▼───────┐ │
│  │ MAX98357  │  │◄────────┼──│ TTS     │◄─│ Database     │ │
│  │ Speaker   │  │         │  │ Engine  │  │ (SQLite)     │ │
│  └───────────┘  │         │  └─────────┘  └──────────────┘ │
│                 │         │                                 │
│  ┌───────────┐  │         │                                 │
│  │ Wake Word │  │         │                                 │
│  │ Detection │  │         │                                 │
│  └───────────┘  │         │                                 │
└─────────────────┘         └─────────────────────────────────┘
```

## Data Flow

### 1. Wake Word Detection (on device)

```
Microphone → Wake Word Model → Trigger Recording
```

The ESP32 continuously listens for "Hey Polly" using a TFLite model running locally.

### 2. Audio Capture & Streaming

```
Microphone → I2S → Audio Buffer → Base64 → WebSocket → Server
```

Once triggered, the ESP32:
1. Captures 16-bit PCM audio at 16kHz
2. Buffers in chunks (~4KB)
3. Base64 encodes each chunk
4. Streams via WebSocket to server

### 3. Server Processing

```
Audio Stream → Whisper → Text → Intent Parser → Database → Response Text
```

The server:
1. Collects audio chunks until end-of-stream
2. Transcribes with Whisper
3. Parses intent (store, retrieve, delete, etc.)
4. Executes against database
5. Generates response text

### 4. Response Playback

```
Response Text → TTS → WAV → Base64 → WebSocket → ESP32 → I2S → Speaker
```

The server:
1. Converts response to speech
2. Encodes as base64
3. Sends back via same WebSocket

The ESP32:
1. Decodes audio
2. Plays through I2S speaker

## Protocol

### Device → Server

```json
// Connect
{"event": "connect", "device_id": "polly001"}

// Audio chunk
{"event": "audio", "data": "<base64 PCM audio>"}

// End of recording
{"event": "end_stream"}

// Keep-alive
{"event": "ping"}
```

### Server → Device

```json
// Connection acknowledged
{"event": "connected", "message": "Ready to receive audio"}

// Response with audio
{
  "event": "response",
  "text": "The wrench is in the left drawer",
  "audio": "<base64 WAV audio>",
  "intent": "retrieve_item",
  "transcription": "where is the wrench"
}

// Error
{"event": "error", "message": "No audio received"}

// Keep-alive response
{"event": "pong"}
```

## Component Details

### ESP32 Firmware

| File | Purpose |
|------|---------|
| `polly-esp32.ino` | Main state machine |
| `config.h` | WiFi, server, pin configuration |
| `audio_capture.h` | I2S microphone driver |
| `audio_playback.h` | I2S speaker driver |

### Server

| Module | Purpose |
|--------|---------|
| `api/audio.py` | WebSocket handler |
| `api/commands.py` | REST API for web UI |
| `api/devices.py` | Device management |
| `core/intent_parser.py` | NLP command parsing |
| `core/database.py` | SQLite storage |
| `core/transcription.py` | Whisper wrapper |
| `core/tts.py` | Text-to-speech |

## Deployment Options

### Development

```
ESP32 ─── WiFi ─── Your PC/Pi (localhost:8000)
```

Run the server on your development machine or Pi.

### Production

```
ESP32 ─── WiFi ─── Internet ─── Cloud Server (api.polly.io)
```

Deploy server to AWS, GCP, DigitalOcean, etc.

## Future: Polly LOCAL

For the offline version, the architecture changes:

```
┌────────────────────────────────────┐
│           ESP32-S3 Device          │
│                                    │
│  ┌─────────┐  ┌─────────────────┐  │
│  │ Wake    │  │ Command         │  │
│  │ Word    │  │ Recognition     │  │
│  └─────────┘  │ (limited vocab) │  │
│               └────────┬────────┘  │
│                        │           │
│  ┌─────────┐  ┌────────▼────────┐  │
│  │ Pre-    │  │ Flash Memory    │  │
│  │ recorded│  │ (key/value)     │  │
│  │ TTS     │  └─────────────────┘  │
│  └─────────┘                       │
└────────────────────────────────────┘
```

No cloud. No WiFi required. Limited but functional.
