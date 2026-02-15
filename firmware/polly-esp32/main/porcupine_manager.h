#ifndef PORCUPINE_MANAGER_H
#define PORCUPINE_MANAGER_H

#include "esp_err.h"
#include "pv_porcupine.h"
#include <stdint.h>
#include <stdbool.h>

/**
 * Porcupine context structure
 */
typedef struct {
    pv_porcupine_t *handle;
    const char *access_key;
    const void *model_buffer;
    size_t model_size;
    float sensitivity;
    int32_t frame_length;
    int32_t sample_rate;
} porcupine_ctx_t;

/**
 * Initialize Porcupine wake word engine
 *
 * @param ctx Porcupine context to initialize
 * @return ESP_OK on success, ESP_FAIL on error
 */
esp_err_t porcupine_init(porcupine_ctx_t *ctx);

/**
 * Process an audio frame for wake word detection
 *
 * @param ctx Porcupine context
 * @param pcm PCM audio frame (512 samples, 16-bit)
 * @return true if wake word detected, false otherwise
 */
bool porcupine_process_frame(porcupine_ctx_t *ctx, const int16_t *pcm);

/**
 * Clean up and destroy Porcupine instance
 *
 * @param ctx Porcupine context to destroy
 */
void porcupine_destroy(porcupine_ctx_t *ctx);

#endif // PORCUPINE_MANAGER_H
