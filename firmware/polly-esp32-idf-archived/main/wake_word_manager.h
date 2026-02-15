#ifndef WAKE_WORD_MANAGER_H
#define WAKE_WORD_MANAGER_H

#include "esp_err.h"
#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Wake word manager context (opaque)
 */
typedef struct wake_word_ctx wake_word_ctx_t;

/**
 * Callback function when wake word is detected
 */
typedef void (*wake_word_callback_t)(const char *wake_word);

/**
 * Initialize wake word detection system
 *
 * @param callback Function to call when wake word detected
 * @return ESP_OK on success, error code otherwise
 */
esp_err_t wake_word_init(wake_word_callback_t callback);

/**
 * Start wake word detection
 *
 * @return ESP_OK on success, error code otherwise
 */
esp_err_t wake_word_start(void);

/**
 * Process audio frame for wake word detection
 * Should be called continuously with new audio frames
 *
 * @return ESP_OK on success, error code otherwise
 */
esp_err_t wake_word_loop(void);

/**
 * Stop wake word detection
 */
void wake_word_stop(void);

/**
 * Clean up wake word detection system
 */
void wake_word_destroy(void);

#ifdef __cplusplus
}
#endif

#endif // WAKE_WORD_MANAGER_H
