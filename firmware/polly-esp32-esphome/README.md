# Polly ESP32-S3 Voice Assistant (ESPHome + microWakeWord)

On-device wake word detection using **microWakeWord** integrated with Home Assistant and Polly Connect server.

## Why ESPHome + Home Assistant?

✅ **microWakeWord ecosystem** - Access to [hundreds of community wake words](https://github.com/TaterTotterson/microWakeWords)
✅ **Easy customization** - YAML configuration instead of C++ programming
✅ **Proven and stable** - Used by thousands in Home Assistant community
✅ **OTA updates** - Update firmware wirelessly
✅ **Web dashboard** - Monitor and control from browser

## Hardware Requirements

### Required:
1. **ESP32-S3 Development Board** with PSRAM (8MB recommended)
2. **INMP441 I2S MEMS Microphone** (~$2-5)

### Optional:
3. **RGB LED** for status indication (WS2812 or discrete RGB)

### Wiring Diagram (INMP441 → ESP32-S3):

```
INMP441 Pin    ESP32-S3 GPIO    Purpose
-----------    -------------    -------
WS             GPIO 42          I2S Word Select (LRCLK)
SD             GPIO 41          I2S Serial Data (DIN)
SCK            GPIO 40          I2S Serial Clock (BCLK)
L/R            GND              Channel Select (Left)
VDD            3.3V             Power
GND            GND              Ground
```

**Optional RGB LED:**
```
LED Pin        ESP32-S3 GPIO
-------        -------------
Red            GPIO 48
Green          GPIO 47
Blue           GPIO 21
GND            GND
```

## Software Requirements

### 1. Install Home Assistant

**Option A: Run on Same Computer as Polly Server**
```bash
# Install Home Assistant Core (Python)
python3 -m pip install homeassistant
hass
```
Access at: `http://localhost:8123`

**Option B: Separate Raspberry Pi / VM**
- Download Home Assistant OS: https://www.home-assistant.io/installation/
- Flash to SD card or install in VM
- Access at: `http://homeassistant.local:8123`

**Option C: Docker (Recommended for Testing)**
```bash
docker run -d \
  --name homeassistant \
  --privileged \
  --restart=unless-stopped \
  -e TZ=America/New_York \
  -v /PATH_TO_YOUR_CONFIG:/config \
  --network=host \
  ghcr.io/home-assistant/home-assistant:stable
```

### 2. Install ESPHome in Home Assistant

1. Open Home Assistant web interface
2. Go to **Settings** → **Add-ons**
3. Click **Add-on Store**
4. Search for **ESPHome**
5. Click **Install**
6. Start the ESPHome add-on
7. Open the ESPHome web UI

### 3. Install ESPHome CLI (Alternative)

If you prefer command-line:
```bash
pip install esphome
```

## Setup Steps

### Step 1: Configure Secrets

Edit `secrets.yaml`:
```yaml
wifi_ssid: "YourWiFiSSID"
wifi_password: "YourWiFiPassword"
api_encryption_key: ""  # Will be auto-generated
ota_password: "polly-ota-password"
```

Generate API encryption key:
```bash
openssl rand -base64 32
```

### Step 2: Compile and Flash Firmware

**Using ESPHome Dashboard (Easiest):**
1. Open ESPHome in Home Assistant
2. Click **+ New Device**
3. Give it a name: `polly-voice-assistant`
4. Choose **ESP32-S3**
5. Copy the contents of `polly-voice-assistant.yaml` into the editor
6. Click **Install** → **Plug into this computer**
7. Select the USB port and flash

**Using ESPHome CLI:**
```bash
cd firmware/polly-esp32-esphome

# Compile
esphome compile polly-voice-assistant.yaml

# Flash (ESP32 connected via USB)
esphome upload polly-voice-assistant.yaml
```

### Step 3: Verify Connection

1. Device should appear in Home Assistant **Settings** → **Devices & Services**
2. Click **Configure** and enter API encryption key
3. Device should show as "Online"

### Step 4: Test Wake Word Detection

1. Say **"Okay Nabu"** into the microphone
2. Watch the logs in ESPHome dashboard
3. LED should turn green when wake word detected
4. LED should turn blue when listening for command

**Check logs:**
```bash
esphome logs polly-voice-assistant.yaml
```

Expected output:
```
[microWakeWord] Wake word detected: Okay Nabu
[voice_assistant] Listening for command...
```

### Step 5: Bridge to Polly Server

#### A. Update Polly Server

The server has been updated with a new endpoint: `/api/commands/process`

This endpoint receives voice commands from Home Assistant and processes them through your Polly intent parser and database.

#### B. Configure Home Assistant Automation

1. In Home Assistant, go to **Settings** → **Automations & Scenes**
2. Click **Create Automation**
3. Choose **Start with an empty automation**
4. Switch to **YAML mode** (three dots menu)
5. Paste the contents from `home-assistant-config/polly-bridge-automation.yaml`
6. **Important**: Replace `YOUR_POLLY_SERVER_IP` with your actual server IP
7. Save the automation

**Or manually add to `configuration.yaml`:**
```yaml
# Add this to your Home Assistant configuration.yaml
automation: !include automations.yaml
rest_command: !include rest_commands.yaml
```

Then create `rest_commands.yaml`:
```yaml
polly_send_command:
  url: "http://192.168.1.100:8000/api/commands/process"
  method: POST
  content_type: "application/json"
  payload: >
    {
      "transcription": "{{ transcription }}",
      "device_id": "{{ device_id }}",
      "source": "home_assistant"
    }
```

### Step 6: Test End-to-End

1. **Start Polly Server:**
   ```bash
   cd server
   python main.py
   ```

2. **Say wake word:** "Okay Nabu"
3. **Say command:** "My keys are in the kitchen"
4. **Check Polly server logs:**
   ```
   [homeassistant] Received command: My keys are in the kitchen
   [intent_parser] Intent: store
   [database] Stored: keys → kitchen
   ```

5. **Test retrieval:**
   - Say: "Okay Nabu"
   - Say: "Where are my keys?"
   - Server should respond: "The keys are in the kitchen."

## Available Wake Words

### Pre-installed:
- **okay_nabu** (default)
- **hey_jarvis**
- **alexa**
- **hey_mycroft**

### Change Wake Word:

Edit `polly-voice-assistant.yaml`:
```yaml
micro_wake_word:
  model: hey_jarvis  # Change this line
  probability_cutoff: 0.97
  sliding_window_average_size: 5
```

Then reflash:
```bash
esphome upload polly-voice-assistant.yaml
```

### Use Community Wake Words:

Browse available models:
- https://github.com/TaterTotterson/microWakeWords
- https://github.com/esphome/micro-wake-word-models

Example using custom wake word from GitHub:
```yaml
micro_wake_word:
  models:
    - model: https://github.com/TaterTotterson/microWakeWords/raw/main/models/v2/computer.tflite
```

### Create Your Own Custom Wake Word:

1. Visit: https://www.kevinahrendt.com/micro-wake-word
2. Follow the training guide using Google Colab (free)
3. Download the `.tflite` model file
4. Host it on GitHub or local webserver
5. Reference it in your ESPHome config

**Or request from community:**
- Post in Home Assistant forums
- Many community members train wake words for others
- See: https://community.home-assistant.io

## Troubleshooting

### Wake word not detected

**Check microphone:**
```bash
esphome logs polly-voice-assistant.yaml
```

Look for I2S audio initialization:
```
[i2s_audio] Initializing I2S...
[microphone] Microphone started
```

**Adjust sensitivity:**
```yaml
micro_wake_word:
  probability_cutoff: 0.90  # Lower = more sensitive (default: 0.97)
  sliding_window_average_size: 3  # Lower = faster detection (default: 5)
```

**Check wiring:**
- INMP441 L/R pin MUST be connected to GND
- Verify GPIO pins match your configuration
- Check 3.3V power supply is stable

### Home Assistant not receiving commands

**Check automation:**
1. Go to **Settings** → **Automations & Scenes**
2. Find "Polly Voice Assistant Bridge"
3. Click **Run** to manually trigger
4. Check **Trace** for errors

**Check Polly server:**
```bash
curl -X POST http://localhost:8000/api/commands/process \
  -H "Content-Type: application/json" \
  -d '{"transcription":"test command","device_id":"test"}'
```

### ESP32 won't connect to WiFi

**Check secrets.yaml:**
- SSID is correct (case-sensitive)
- Password is correct
- WiFi is 2.4GHz (ESP32 doesn't support 5GHz)

**Enable fallback hotspot:**
1. ESP32 creates WiFi network: `polly-voice-assistant Fallback`
2. Password: `polly12345`
3. Connect and reconfigure WiFi

### OTA updates fail

**Use USB:**
```bash
esphome upload polly-voice-assistant.yaml --device /dev/ttyUSB0
```

**Increase timeout:**
```yaml
ota:
  - platform: esphome
    password: !secret ota_password
    safe_mode: true
    reboot_timeout: 15min
```

## Architecture Diagram

```
┌─────────────┐
│   INMP441   │ Microphone
└──────┬──────┘
       │ I2S Audio (16kHz)
       ↓
┌──────────────────────────────┐
│      ESP32-S3 (ESPHome)      │
│  ┌────────────────────────┐  │
│  │   microWakeWord        │  │
│  │   "Okay Nabu" → ✓      │  │
│  └───────────┬────────────┘  │
│              ↓                │
│  ┌────────────────────────┐  │
│  │   Voice Assistant      │  │
│  │   Record command audio │  │
│  └───────────┬────────────┘  │
└──────────────┼───────────────┘
               │ Home Assistant API
               ↓
┌──────────────────────────────┐
│      Home Assistant          │
│  ┌────────────────────────┐  │
│  │  Whisper (Transcribe)  │  │
│  │  "my keys are..."      │  │
│  └───────────┬────────────┘  │
│              ↓                │
│  ┌────────────────────────┐  │
│  │  Automation Bridge     │  │
│  │  Forward to Polly      │  │
│  └───────────┬────────────┘  │
└──────────────┼───────────────┘
               │ HTTP POST
               ↓
┌──────────────────────────────┐
│    Polly Connect Server      │
│  ┌────────────────────────┐  │
│  │  Intent Parser         │  │
│  │  "store: keys→kitchen" │  │
│  └───────────┬────────────┘  │
│              ↓                │
│  ┌────────────────────────┐  │
│  │  Database              │  │
│  │  Save location         │  │
│  └────────────────────────┘  │
└──────────────────────────────┘
```

## Performance

- **Wake Word Latency**: <100ms
- **End-to-End**: ~2-3 seconds (wake → response)
- **Bandwidth**: ~50KB for 5-second command
- **Power**: ~150mA @ 3.3V during listening

## Customization

### Add Speaker for TTS Response

```yaml
# Add I2S speaker (MAX98357A)
i2s_audio:
  - id: i2s_out
    i2s_lrclk_pin: GPIO13
    i2s_bclk_pin: GPIO12

speaker:
  - platform: i2s_audio
    id: speaker
    dac_type: external
    i2s_dout_pin: GPIO14
    mode: mono

# Update voice assistant to use speaker
voice_assistant:
  microphone: mic
  speaker: speaker  # Add this line
```

### Change LED Pins

Update the `output` section:
```yaml
output:
  - platform: ledc
    id: led_red
    pin: GPIO1  # Change to your red LED pin
  - platform: ledc
    id: led_green
    pin: GPIO2  # Change to your green LED pin
  - platform: ledc
    id: led_blue
    pin: GPIO3  # Change to your blue LED pin
```

### Multiple Wake Words

```yaml
micro_wake_word:
  models:
    - model: okay_nabu
    - model: hey_jarvis
    - model: alexa
```

ESP32-S3 can run up to 4 models simultaneously!

## Resources

- **ESPHome Documentation**: https://esphome.io
- **microWakeWord**: https://www.kevinahrendt.com/micro-wake-word
- **Community Wake Words**: https://github.com/TaterTotterson/microWakeWords
- **Home Assistant**: https://www.home-assistant.io
- **Polly Connect**: [Your GitHub repo]

## Support

For issues:
1. Check ESPHome logs first
2. Verify Home Assistant automation
3. Test Polly server endpoint manually
4. Ask in Home Assistant community forums

## License

This project integrates multiple open-source components:
- ESPHome: MIT License
- microWakeWord: Apache 2.0
- Home Assistant: Apache 2.0
