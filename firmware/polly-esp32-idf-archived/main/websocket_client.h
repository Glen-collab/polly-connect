#ifndef WEBSOCKET_CLIENT_H
#define WEBSOCKET_CLIENT_H

#include "esp_err.h"
#include "cJSON.h"
#include <stdint.h>
#include <stdbool.h>

/**
 * Callback for WebSocket events from server
 *
 * @param event JSON event object from server
 */
typedef void (*websocket_event_callback_t)(cJSON *event);

/**
 * Initialize WebSocket client and connect to server
 *
 * @param uri WebSocket URI (e.g., "ws://192.168.1.100:8000/api/audio/stream")
 * @param callback Callback function for server events
 * @return ESP_OK on success, error code otherwise
 */
esp_err_t websocket_client_init(const char *uri,
                                 websocket_event_callback_t callback);

/**
 * Send wake_word_detected event to server
 *
 * @return ESP_OK on success, error code otherwise
 */
esp_err_t websocket_send_wake_detected(void);

/**
 * Send audio stream data to server
 *
 * @param audio_b64 Base64-encoded audio data
 * @param len Length of Base64 string
 * @return ESP_OK on success, error code otherwise
 */
esp_err_t websocket_send_audio(const uint8_t *audio_b64, size_t len);

/**
 * Send command_end event to server
 *
 * @return ESP_OK on success, error code otherwise
 */
esp_err_t websocket_send_command_end(void);

/**
 * Check if WebSocket is connected
 *
 * @return true if connected, false otherwise
 */
bool websocket_is_connected(void);

#endif // WEBSOCKET_CLIENT_H
