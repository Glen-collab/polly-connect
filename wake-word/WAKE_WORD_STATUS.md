# Wake Word Training Status

## Current State: v3 Model Working!

| Version | Recall | False Positive Rate | Notes |
|---------|--------|-------------------|-------|
| v1 | 0% | 0% | Said "no" to everything |
| v2 | 100% | 100% | Said "yes" to everything |
| **v3** | **57% (55/96)** | **8% (12/149)** | **Usable!** |

**v3 training stats (from Colab):**
- Accuracy: 74%, Recall: 73.2%, False Positives/Hour: 0.0
- 3 training sequences (10000 + 1000 + 1000 steps)
- Trained with 5000 synthetic Piper TTS samples + 96 real positives
- 4 Piper voices: libritts_r (904 speakers), lessac, amy, cori
- Augmented across 254 batches with room impulse responses + background noise

**v3 local test results:**
- Positive avg score: 0.494, most detections score 0.8+
- Negative avg score: 0.075, most score 0.001
- 12 false positives worth investigating (could be phonetically similar phrases)
- Threshold 0.5 — lowering to 0.4 would improve recall but increase false positives

### Files on PC
- `hey_polly.onnx` + `hey_polly.onnx.data` — v3 model (working)
- `test_model.py` — Local test script (`py test_model.py`)
- `COLAB_CLEAN_SLATE.md` — Battle-tested Colab training guide (v3)
- `positive/` — 96 real "Hey Polly" samples
- `negative/` — 149 real non-wake-word samples
- `record_samples.py` / `analyze_samples.py` — Sample recording/analysis tools
- `hey_polly_samples.zip` — Zipped samples for Colab upload

### Google Drive Backup
- `My Drive/hey_polly_training/` — Model + training log + augmented data

## Hardware (ESP32-S3-WROOM-1-N16R8)
- **Mic:** INMP441 — SCK=GPIO6, WS=GPIO5, SD=GPIO4
- **Speaker:** MAX98357A — BCLK=GPIO12, LRC=GPIO11, DIN=GPIO10
- **LED:** GPIO48
- **Flash:** 16MB, **PSRAM:** 8MB Octal

## Firmware Options

### Option A: Server-Side Wake Word (Fastest to Deploy)
The .onnx model can't run directly on ESP32-S3 (OpenWakeWord is too heavy). Instead:
1. ESP32 streams audio to Polly server over WiFi
2. Server runs OpenWakeWord with `hey_polly.onnx`
3. On detection → server signals ESP32 to start recording command
4. Server runs Whisper STT → processes → returns TTS audio

**Pros:** Uses the model we just trained, no conversion needed
**Cons:** Requires WiFi connection, slight latency, server must be running

### Option B: ESPHome + microWakeWord (Best On-Device)
The ESPHome config (`firmware/polly-esp32-esphome/polly-voice-assistant.yaml`) already has microWakeWord set up with "okay_nabu". To use a custom "Hey Polly":
1. Retrain using microWakeWord's training pipeline (separate from OpenWakeWord)
2. Produces a .tflite model optimized for ESP32-S3
3. Load custom model in ESPHome config
4. Integrates with Home Assistant voice pipeline

**Pros:** Fully on-device wake word, low latency, works offline
**Cons:** Requires retraining with microWakeWord pipeline, needs Home Assistant

### Option C: ESP-IDF Standalone (Current Firmware)
The ESP-IDF firmware (`firmware/polly-s3-wakeword/`) uses ESP-SR WakeNet with "Hi ESP":
- Could swap to server-side detection (Option A hybrid)
- ESP-SR WakeNet uses its own model format, can't load .onnx directly
- Self-contained, talks directly to Polly FastAPI server

## What Needs to Happen Next

### Step 1: Choose Deployment Path
- **Option A** is fastest — just add an audio streaming endpoint to the server
- **Option B** is best long-term — on-device detection, no server dependency for wake word

### Step 2: Server Endpoint (for Option A or as fallback)
- Add WebSocket or HTTP streaming endpoint to FastAPI server
- Run OpenWakeWord with `hey_polly.onnx` on incoming audio
- After detection: Whisper STT → process query → TTS response

### Step 3: Flash and Test
- Update WiFi credentials in firmware for home network
- Install ESP-IDF v5.4.x (if using Option C) or ESPHome (if Option B)
- Build, flash, test end-to-end

### Step 4: Improve Model (Optional)
- Record more samples (200+ positive, 300+ negative)
- Investigate the 12 false positive negative samples
- Retrain with more Piper voices and higher augmentation rounds
- Target: 80%+ recall with <3% false positives

## Colab Training Guide
See `COLAB_CLEAN_SLATE.md` for the full, tested Colab notebook guide. All dependency issues and patches are documented and built into the cells.

## Recording More Samples
```bash
cd C:\Users\big_g\Desktop\polly-connect\wake-word
python record_samples.py positive    # say "Hey Polly" naturally
python record_samples.py negative    # say other phrases, background noise
python record_samples.py review      # listen back to recordings
python analyze_samples.py            # check quality
```
