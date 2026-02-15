# ARCHIVED: ESP-IDF Porcupine Implementation

This directory contains an **archived** ESP-IDF firmware implementation using Picovoice Porcupine.

## Why Archived?

This approach was **replaced** with the ESPHome + microWakeWord implementation in `polly-esp32-esphome/` because:

1. **Porcupine doesn't officially support ESP32-S3** - Library files not readily available
2. **microWakeWord has huge community** - Hundreds of free custom wake words
3. **ESPHome is easier** - YAML configuration instead of C programming
4. **Better ecosystem** - Home Assistant integration, OTA updates, web dashboard

## What's Here?

This is a complete ESP-IDF firmware implementation that was designed to:
- Use Picovoice Porcupine for wake word detection
- Interface with INMP441 I2S microphone
- Connect directly to Polly Connect server via WebSocket
- Run on bare metal (no middleware)

**Status**: Incomplete - Porcupine library integration was not finished

## Should You Use This?

**NO** - Use the ESPHome implementation instead (`../polly-esp32-esphome/`)

This code is kept for reference only.

## If You Really Want ESP-IDF...

Consider using:
- **Espressif WakeNet** - Official ESP32 wake word solution
- **Porcupine Arduino** - Simpler than ESP-IDF, has official library support
- **microWakeWord standalone** - More complex but possible

See: https://github.com/0xD34D/micro_wake_word_standalone
