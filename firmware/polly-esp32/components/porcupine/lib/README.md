# Porcupine Library

Place the pre-compiled Porcupine library for ESP32-S3 here:

**File**: `libpv_porcupine.a`

## Download Instructions

1. Visit the Porcupine GitHub repository:
   https://github.com/Picovoice/porcupine

2. Navigate to: `lib/esp32/`

3. Download the appropriate library for ESP32-S3:
   - Look for `libpv_porcupine.a` or ESP32-S3 specific version

4. Place the downloaded file in this directory

## Alternative: Download via wget

```bash
cd firmware/polly-esp32/components/porcupine/lib/

# Check Porcupine releases for the correct download URL
wget https://github.com/Picovoice/porcupine/raw/master/lib/esp32/libpv_porcupine.a
```

**Note**: The exact path may vary depending on Porcupine version. Check the latest
repository structure for the correct location.
