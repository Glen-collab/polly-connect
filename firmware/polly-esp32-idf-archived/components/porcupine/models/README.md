# Porcupine Wake Word Models

Place your wake word model file(s) here.

## Built-in Wake Words

Download pre-trained models from Porcupine repository:
https://github.com/Picovoice/porcupine/tree/master/resources/keyword_files

### Available Built-in Wake Words for ESP32:
- `jarvis_esp.ppn` - "Jarvis"
- `alexa_esp.ppn` - "Alexa"
- `computer_esp.ppn` - "Computer"
- `hey_google_esp.ppn` - "Hey Google"
- `ok_google_esp.ppn` - "Ok Google"
- `picovoice_esp.ppn` - "Picovoice"

## Download Example (Jarvis):

```bash
cd firmware/polly-esp32/components/porcupine/models/

wget https://github.com/Picovoice/porcupine/raw/master/resources/keyword_files/esp32/jarvis_esp.ppn
```

## Custom Wake Words

To create a custom wake word:

1. Go to Picovoice Console: https://console.picovoice.ai/
2. Sign in with your account
3. Navigate to "Porcupine" section
4. Click "Train New Wake Word"
5. Enter your custom phrase
6. Train the model
7. Download the `.ppn` file for ESP32 platform
8. Place it in this directory
9. Update `porcupine_manager.c` to reference your model file

**Note**: Custom wake words require a Picovoice subscription plan.

## Using a Different Wake Word

If you want to use a different wake word than "jarvis":

1. Download or create your wake word model (e.g., `my_wake_word_esp.ppn`)
2. Place it in this directory
3. Update `components/porcupine/CMakeLists.txt`:
   ```cmake
   target_add_binary_data(${COMPONENT_LIB}
       "${CMAKE_CURRENT_SOURCE_DIR}/models/my_wake_word_esp.ppn"
       BINARY
   )
   ```
4. Update `main/porcupine_manager.c` to reference the new binary symbols:
   ```c
   extern const uint8_t my_wake_word_esp_ppn_start[] asm("_binary_my_wake_word_esp_ppn_start");
   extern const uint8_t my_wake_word_esp_ppn_end[]   asm("_binary_my_wake_word_esp_ppn_end");
   ```
