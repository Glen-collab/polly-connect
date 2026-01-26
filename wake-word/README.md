# Wake Word Training - "Hey Polly"

This folder contains assets for training a custom wake word model.

## Current Status

Currently using **"Hey Jarvis"** from OpenWakeWord as a placeholder. Custom "Hey Polly" training is Phase 4.

## Training Process

### 1. Collect Audio Samples

**Positive samples** (47 recorded):
- Clear "Hey Polly" recordings
- Multiple speakers if possible
- Various distances from mic
- Different ambient noise levels

**Negative samples** (20 recorded):
- Random speech not containing wake word
- Common phrases that sound similar
- Background noise

### 2. Use Google Colab for Training

1. Go to [Google Colab](https://colab.research.google.com)
2. Open the OpenWakeWord training notebook:
   ```
   https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb
   ```
3. Change runtime to **T4 GPU** (Runtime → Change runtime type)
4. Upload your samples:
   - `positive/` → "Hey Polly" clips
   - `negative/` → non-wake-word clips
5. Run all cells
6. Download the trained model (`.onnx` or `.tflite`)

### 3. Deploy to ESP32

**Option A: TFLite (recommended)**
- Smaller model size
- Native ESP32 support via TensorFlow Lite Micro
- Convert ONNX to TFLite if needed

**Option B: Edge Impulse**
- User-friendly web interface
- Handles conversion automatically
- Free tier available

### 4. Integration

Place the model file in `firmware/polly-esp32/` and update wake word detection code.

## Sample Requirements

### Recording Tips

- Use same mic type as target device (INMP441)
- 16kHz sample rate, mono
- 1-2 seconds per clip
- Include slight variations:
  - "Hey Polly"
  - "Hey, Polly"
  - "Hey Polly?"

### File Format

- WAV files preferred
- 16-bit PCM
- Naming: `positive_001.wav`, `negative_001.wav`

## Alternative: Picovoice Porcupine

For production, consider [Picovoice Porcupine](https://picovoice.ai/):
- Professional-grade accuracy
- Easy custom wake word training
- Free tier for personal use
- Native ESP32 support

## Resources

- [OpenWakeWord](https://github.com/dscripka/openWakeWord)
- [Edge Impulse](https://www.edgeimpulse.com/)
- [Picovoice Porcupine](https://picovoice.ai/platform/porcupine/)
- [TensorFlow Lite Micro](https://www.tensorflow.org/lite/microcontrollers)
