#ifndef AUDIO_CAPTURE_H
#define AUDIO_CAPTURE_H

#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include <stdint.h>
#include <stddef.h>

/**
 * Initialize I2S audio capture with INMP441 microphone
 *
 * @param queue Queue to send audio frames to
 * @return ESP_OK on success, error code otherwise
 */
esp_err_t audio_capture_init(QueueHandle_t queue);

/**
 * Audio capture task - reads from I2S and sends to queue
 *
 * @param pvParameters Task parameters (unused)
 */
void audio_capture_task(void *pvParameters);

/**
 * Get pointer to the circular pre-wake audio buffer
 *
 * @param num_frames Output parameter for number of frames in buffer
 * @return Pointer to circular buffer
 */
int16_t* audio_capture_get_prebuffer(size_t *num_frames);

/**
 * Get current index in circular buffer
 *
 * @return Current buffer index
 */
size_t audio_capture_get_buffer_index(void);

#endif // AUDIO_CAPTURE_H
