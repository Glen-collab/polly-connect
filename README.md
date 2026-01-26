# 🦜 Polly Connect

**ESP32-based voice assistant for garage/workshop storage management**

Tell Polly where you put things, ask her later. Simple as that.

```
"Hey Polly, the wrench is in the left drawer"
    ... later ...
"Hey Polly, where's my wrench?"
    → "The wrench is in the left drawer"
```

## Architecture

```
┌─────────────────┐         ┌─────────────────┐
│   ESP32 Device  │  WiFi   │   Cloud Server  │
│   (Ears/Mouth)  │◄───────►│    (Brain)      │
│                 │         │                 │
│ • Wake word     │         │ • Whisper STT   │
│ • Audio capture │         │ • Intent parse  │
│ • Audio output  │         │ • Database      │
└─────────────────┘         │ • TTS           │
                            └─────────────────┘
```

**ESP32** handles audio I/O and wake word detection.  
**Server** handles the "smarts" — transcription, understanding, responses.

## Hardware Requirements

| Part | Purpose | ~Price |
|------|---------|--------|
| ESP32-WROOM-32 | Microcontroller | $6 |
| INMP441 | I2S Microphone | $3 |
| MAX98357A | I2S Amplifier | $4 |
| Small Speaker | Audio output | $3 |

**Total: ~$16-20** (vs $100+ for Raspberry Pi build)

## Quick Start

### 1. Server Setup

```bash
cd server

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Run server
python main.py
```

Server runs at `http://localhost:8000`

### 2. ESP32 Setup

1. Install [Arduino IDE](https://www.arduino.cc/en/software)
2. Add ESP32 board support (see [docs/wiring.md](docs/wiring.md))
3. Install libraries:
   - WebSocketsClient
   - ArduinoJson
   - Base64
4. Edit `firmware/polly-esp32/config.h`:
   ```cpp
   #define WIFI_SSID     "your_wifi"
   #define WIFI_PASSWORD "your_password"
   #define SERVER_HOST   "192.168.1.100"  // Your server IP
   ```
5. Upload to ESP32

### 3. Wire It Up

See [docs/wiring.md](docs/wiring.md) for detailed pinout.

Quick reference:
```
INMP441 Mic → ESP32          MAX98357A Amp → ESP32
-----------   -----          -------------   -----
VDD → 3.3V                   VIN → 5V
GND → GND                    GND → GND
SD  → GPIO32                 DIN → GPIO22
WS  → GPIO25                 BCLK → GPIO26
SCK → GPIO33                 LRC → GPIO21
L/R → GND
```

### 4. Test It

1. Open Serial Monitor (115200 baud)
2. Press 'r' to start recording (wake word coming in Phase 4)
3. Speak: "The hammer is on the pegboard"
4. Listen for response

## Project Structure

```
polly-connect/
├── server/                 # Cloud brain (Python/FastAPI)
│   ├── api/                # REST and WebSocket endpoints
│   ├── core/               # Business logic
│   │   ├── intent_parser.py    # NLP command parsing
│   │   ├── database.py         # SQLite storage
│   │   ├── transcription.py    # Whisper STT
│   │   └── tts.py              # Text-to-speech
│   └── main.py             # Entry point
│
├── firmware/               # ESP32 code (Arduino)
│   └── polly-esp32/
│       ├── polly-esp32.ino     # Main sketch
│       ├── config.h            # Configuration
│       ├── audio_capture.h     # Mic driver
│       └── audio_playback.h    # Speaker driver
│
├── wake-word/              # Wake word training assets
│   ├── positive/           # "Hey Polly" samples
│   └── negative/           # Non-wake-word samples
│
└── docs/                   # Documentation
    ├── architecture.md
    ├── wiring.md
    └── api.md
```

## Build Phases

- [x] **Phase 1:** Hardware test (mic + speaker working)
- [ ] **Phase 2:** WiFi streaming (ESP32 → Server)
- [ ] **Phase 3:** Cloud brain (Whisper + intent + TTS)
- [ ] **Phase 4:** Wake word ("Hey Polly")
- [ ] **Phase 5:** Optimization (latency, silence detection)

## Voice Commands

| You say... | Polly does... |
|------------|---------------|
| "The hammer is on the pegboard" | Stores location |
| "Where is the hammer?" | Retrieves location |
| "What's in the red bin?" | Lists items in location |
| "Forget the old screwdriver" | Deletes item |
| "List everything" | Shows all items |

## API

REST API available at `http://localhost:8000/api/`:

```bash
# Natural language command
curl -X POST http://localhost:8000/api/command \
  -H "Content-Type: application/json" \
  -d '{"text": "where is the wrench"}'

# List all items
curl http://localhost:8000/api/items

# Get stats
curl http://localhost:8000/api/stats
```

See [docs/api.md](docs/api.md) for full reference.

## Roadmap

### Polly CONNECT (this repo)
- [x] ESP32 + cloud architecture
- [ ] Full voice pipeline
- [ ] Web dashboard
- [ ] Multi-device support
- [ ] User accounts

### Polly LOCAL (future)
- [ ] Fully offline ESP32-S3 version
- [ ] Limited command vocabulary
- [ ] No cloud required
- [ ] ~$25 total cost

## Credits

Ported from [The Parrot](https://github.com/Glen-collab/parrot) - original Raspberry Pi version.

## License

MIT - Do whatever you want with it.

---

Made for messy garages everywhere. 🔧
