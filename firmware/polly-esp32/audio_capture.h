/**
 * Audio Capture Module - INMP441 I2S Microphone
 */

#ifndef AUDIO_CAPTURE_H
#define AUDIO_CAPTURE_H

#include <driver/i2s.h>
#include "config.h"

// I2S port for microphone
#define I2S_MIC_PORT I2S_NUM_0

/**
 * Initialize the I2S microphone
 * Returns true on success
 */
bool initMicrophone() {
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 256,
    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };
  
  i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_MIC_SERIAL_CLOCK,
    .ws_io_num = I2S_MIC_WORD_SELECT,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = I2S_MIC_SERIAL_DATA
  };
  
  esp_err_t err = i2s_driver_install(I2S_MIC_PORT, &i2s_config, 0, NULL);
  if (err != ESP_OK) {
    Serial.printf("Failed to install I2S mic driver: %d\n", err);
    return false;
  }
  
  err = i2s_set_pin(I2S_MIC_PORT, &pin_config);
  if (err != ESP_OK) {
    Serial.printf("Failed to set I2S mic pins: %d\n", err);
    return false;
  }
  
  // Clear any initial noise
  i2s_zero_dma_buffer(I2S_MIC_PORT);
  
  return true;
}

/**
 * Read audio samples from microphone
 * Returns number of bytes read
 */
size_t readMicrophoneSamples(int16_t* samples, size_t maxSamples) {
  size_t bytesRead = 0;
  
  esp_err_t err = i2s_read(
    I2S_MIC_PORT,
    samples,
    maxSamples * sizeof(int16_t),
    &bytesRead,
    portMAX_DELAY
  );
  
  if (err != ESP_OK) {
    Serial.printf("I2S read error: %d\n", err);
    return 0;
  }
  
  return bytesRead;
}

/**
 * Stop and cleanup microphone
 */
void deinitMicrophone() {
  i2s_driver_uninstall(I2S_MIC_PORT);
}

#endif // AUDIO_CAPTURE_H
