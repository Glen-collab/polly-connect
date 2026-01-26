/**
 * Audio Playback Module - MAX98357A I2S Amplifier
 */

#ifndef AUDIO_PLAYBACK_H
#define AUDIO_PLAYBACK_H

#include <driver/i2s.h>
#include "config.h"

// I2S port for speaker
#define I2S_SPK_PORT I2S_NUM_1

/**
 * Initialize the I2S speaker/amplifier
 * Returns true on success
 */
bool initSpeaker() {
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 256,
    .use_apll = false,
    .tx_desc_auto_clear = true,
    .fixed_mclk = 0
  };
  
  i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_SPK_SERIAL_CLOCK,
    .ws_io_num = I2S_SPK_WORD_SELECT,
    .data_out_num = I2S_SPK_SERIAL_DATA,
    .data_in_num = I2S_PIN_NO_CHANGE
  };
  
  esp_err_t err = i2s_driver_install(I2S_SPK_PORT, &i2s_config, 0, NULL);
  if (err != ESP_OK) {
    Serial.printf("Failed to install I2S speaker driver: %d\n", err);
    return false;
  }
  
  err = i2s_set_pin(I2S_SPK_PORT, &pin_config);
  if (err != ESP_OK) {
    Serial.printf("Failed to set I2S speaker pins: %d\n", err);
    return false;
  }
  
  return true;
}

/**
 * Play raw audio data (16-bit PCM)
 */
void playAudio(const uint8_t* data, size_t length) {
  // Skip WAV header if present (44 bytes)
  size_t offset = 0;
  if (length > 44 && data[0] == 'R' && data[1] == 'I' && data[2] == 'F' && data[3] == 'F') {
    offset = 44;
  }
  
  size_t bytesWritten = 0;
  size_t remaining = length - offset;
  const uint8_t* ptr = data + offset;
  
  while (remaining > 0) {
    size_t toWrite = min(remaining, (size_t)1024);
    
    esp_err_t err = i2s_write(
      I2S_SPK_PORT,
      ptr,
      toWrite,
      &bytesWritten,
      portMAX_DELAY
    );
    
    if (err != ESP_OK) {
      Serial.printf("I2S write error: %d\n", err);
      break;
    }
    
    ptr += bytesWritten;
    remaining -= bytesWritten;
  }
}

/**
 * Play a simple tone (for feedback beeps)
 */
void playTone(int frequency, int durationMs) {
  const int sampleCount = (SAMPLE_RATE * durationMs) / 1000;
  int16_t* samples = (int16_t*)malloc(sampleCount * sizeof(int16_t));
  
  if (!samples) {
    Serial.println("Failed to allocate tone buffer");
    return;
  }
  
  // Generate sine wave
  for (int i = 0; i < sampleCount; i++) {
    float t = (float)i / SAMPLE_RATE;
    samples[i] = (int16_t)(16000 * sin(2 * PI * frequency * t));
  }
  
  // Apply simple envelope to avoid clicks
  int fadeLen = min(100, sampleCount / 4);
  for (int i = 0; i < fadeLen; i++) {
    float factor = (float)i / fadeLen;
    samples[i] = (int16_t)(samples[i] * factor);
    samples[sampleCount - 1 - i] = (int16_t)(samples[sampleCount - 1 - i] * factor);
  }
  
  playAudio((uint8_t*)samples, sampleCount * sizeof(int16_t));
  
  free(samples);
}

/**
 * Stop and cleanup speaker
 */
void deinitSpeaker() {
  i2s_driver_uninstall(I2S_SPK_PORT);
}

#endif // AUDIO_PLAYBACK_H
