#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_system.h"
#include "nvs_flash.h"
#include "esp_heap_caps.h"
#include "mbedtls/base64.h"

#include "config.h"
#include "wifi_manager.h"
#include "websocket_client.h"
#include "audio_capture.h"
#include "porcupine_manager.h"
#include "state_machine.h"

static const char *TAG = "main";

// Global handles
static QueueHandle_t audio_queue = NULL;
static porcupine_ctx_t porcupine_ctx;
static TaskHandle_t streaming_task_handle = NULL;

/**
 * Wake word detection task
 * Processes audio frames and detects wake word using Porcupine
 */
void wake_word_task(void *pvParameters)
{
    int16_t *frame = heap_caps_malloc(FRAME_SIZE * sizeof(int16_t),
                                       MALLOC_CAP_8BIT);
    if (!frame) {
        ESP_LOGE(TAG, "Failed to allocate frame buffer for wake word task");
        vTaskDelete(NULL);
        return;
    }

    ESP_LOGI(TAG, "Wake word task started");

    while (1) {
        // Wait for audio frame from capture task
        if (xQueueReceive(audio_queue, frame, portMAX_DELAY) == pdTRUE) {
            // Only process wake word when in IDLE state
            if (state_machine_get() == STATE_IDLE) {
                bool detected = porcupine_process_frame(&porcupine_ctx, frame);

                if (detected) {
                    ESP_LOGI(TAG, "WAKE WORD DETECTED!");

                    // Transition to wake detected state
                    state_machine_set(STATE_WAKE_DETECTED);

                    // Notify streaming task
                    if (streaming_task_handle) {
                        xTaskNotifyGive(streaming_task_handle);
                    }
                }
            }
        }
    }

    free(frame);
    vTaskDelete(NULL);
}

/**
 * Audio streaming task
 * Streams audio to server after wake word detection
 */
void audio_streaming_task(void *pvParameters)
{
    ESP_LOGI(TAG, "Streaming task started");

    // Allocate buffer for Base64 encoding
    uint8_t *base64_buffer = heap_caps_malloc(2048, MALLOC_CAP_8BIT);
    if (!base64_buffer) {
        ESP_LOGE(TAG, "Failed to allocate base64 buffer");
        vTaskDelete(NULL);
        return;
    }

    int16_t *prebuffer = NULL;
    size_t prebuffer_frames = 0;

    while (1) {
        // Wait for wake word notification
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

        ESP_LOGI(TAG, "Starting audio streaming...");

        // Send wake_word_detected event to server
        websocket_send_wake_detected();

        // Get pre-buffered audio (audio captured before wake word)
        prebuffer = audio_capture_get_prebuffer(&prebuffer_frames);
        size_t buffer_idx = audio_capture_get_buffer_index();

        ESP_LOGI(TAG, "Streaming %d frames of pre-buffered audio", prebuffer_frames);

        // Stream pre-buffered audio in correct order (oldest to newest)
        for (size_t i = 0; i < prebuffer_frames; i++) {
            size_t idx = (buffer_idx + i) % prebuffer_frames;
            int16_t *frame_ptr = &prebuffer[idx * FRAME_SIZE];

            // Base64 encode the frame
            size_t b64_len = 0;
            int ret = mbedtls_base64_encode(base64_buffer, 2048, &b64_len,
                                           (const uint8_t *)frame_ptr,
                                           FRAME_SIZE_BYTES);

            if (ret == 0) {
                base64_buffer[b64_len] = '\0';
                websocket_send_audio(base64_buffer, b64_len);
            }

            vTaskDelay(pdMS_TO_TICKS(5));  // Small delay to avoid overwhelming server
        }

        ESP_LOGI(TAG, "Streaming live audio (max %d seconds)...", STREAMING_DURATION_SEC);

        // Stream live audio for specified duration
        int frames_sent = 0;
        int16_t *live_frame = heap_caps_malloc(FRAME_SIZE * sizeof(int16_t),
                                                MALLOC_CAP_8BIT);

        if (live_frame) {
            while (frames_sent < STREAMING_MAX_FRAMES &&
                   state_machine_get() == STATE_WAKE_DETECTED) {
                if (xQueueReceive(audio_queue, live_frame, pdMS_TO_TICKS(100)) == pdTRUE) {
                    // Base64 encode
                    size_t b64_len = 0;
                    int ret = mbedtls_base64_encode(base64_buffer, 2048, &b64_len,
                                                   (const uint8_t *)live_frame,
                                                   FRAME_SIZE_BYTES);

                    if (ret == 0) {
                        base64_buffer[b64_len] = '\0';
                        websocket_send_audio(base64_buffer, b64_len);
                    }

                    frames_sent++;
                }
            }

            free(live_frame);
        }

        // Send command_end event
        websocket_send_command_end();
        ESP_LOGI(TAG, "Audio streaming complete (%d live frames sent)", frames_sent);

        // Transition to processing state (waiting for server response)
        state_machine_set(STATE_PROCESSING);

        // Wait a bit then return to IDLE
        vTaskDelay(pdMS_TO_TICKS(2000));
        state_machine_set(STATE_IDLE);
        ESP_LOGI(TAG, "Ready for next wake word");
    }

    free(base64_buffer);
    vTaskDelete(NULL);
}

/**
 * WebSocket event callback
 * Handles events received from server
 */
void websocket_event_callback(cJSON *event)
{
    cJSON *event_type = cJSON_GetObjectItem(event, "event");
    if (!event_type || !cJSON_IsString(event_type)) {
        return;
    }

    const char *type = event_type->valuestring;

    if (strcmp(type, "connected") == 0) {
        ESP_LOGI(TAG, "Server acknowledged connection");
        state_machine_set(STATE_IDLE);
        ESP_LOGI(TAG, "Ready to detect wake word");

    } else if (strcmp(type, "wake_ack") == 0) {
        ESP_LOGI(TAG, "Server acknowledged wake word");

    } else if (strcmp(type, "response") == 0) {
        cJSON *text = cJSON_GetObjectItem(event, "text");
        cJSON *transcription = cJSON_GetObjectItem(event, "transcription");
        cJSON *intent = cJSON_GetObjectItem(event, "intent");

        if (transcription && cJSON_IsString(transcription)) {
            ESP_LOGI(TAG, "Transcription: %s", transcription->valuestring);
        }

        if (intent && cJSON_IsString(intent)) {
            ESP_LOGI(TAG, "Intent: %s", intent->valuestring);
        }

        if (text && cJSON_IsString(text)) {
            ESP_LOGI(TAG, "Response: %s", text->valuestring);
        }

    } else if (strcmp(type, "audio_chunk") == 0) {
        // TODO: Implement TTS audio playback
        ESP_LOGD(TAG, "Received audio chunk (playback not yet implemented)");
    }
}

/**
 * Main application entry point
 */
void app_main(void)
{
    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "  Polly ESP32-S3 - Porcupine Wake Word");
    ESP_LOGI(TAG, "========================================");

    // Initialize NVS (required for WiFi)
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    // Initialize state machine
    state_machine_init();
    state_machine_set(STATE_CONNECTING);

    // Connect to WiFi
    ESP_LOGI(TAG, "Connecting to WiFi SSID: %s", WIFI_SSID);
    ret = wifi_init_sta();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "WiFi connection failed!");
        state_machine_set(STATE_ERROR);
        return;
    }

    // Initialize Porcupine wake word engine
    ESP_LOGI(TAG, "Initializing Porcupine wake word engine...");
    ret = porcupine_init(&porcupine_ctx);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Porcupine initialization failed!");
        state_machine_set(STATE_ERROR);
        return;
    }

    // Create audio queue for inter-task communication
    audio_queue = xQueueCreate(10, FRAME_SIZE * sizeof(int16_t));
    if (!audio_queue) {
        ESP_LOGE(TAG, "Failed to create audio queue!");
        state_machine_set(STATE_ERROR);
        return;
    }

    // Initialize I2S audio capture
    ESP_LOGI(TAG, "Initializing I2S audio capture...");
    ret = audio_capture_init(audio_queue);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Audio capture initialization failed!");
        state_machine_set(STATE_ERROR);
        return;
    }

    // Initialize WebSocket client
    ESP_LOGI(TAG, "Connecting to server: %s", SERVER_URI);
    ret = websocket_client_init(SERVER_URI, websocket_event_callback);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "WebSocket initialization failed!");
        state_machine_set(STATE_ERROR);
        return;
    }

    // Wait for WebSocket connection
    vTaskDelay(pdMS_TO_TICKS(2000));

    // Create FreeRTOS tasks
    ESP_LOGI(TAG, "Creating tasks...");

    xTaskCreatePinnedToCore(
        audio_capture_task,
        "audio_capture",
        TASK_STACK_AUDIO,
        NULL,
        TASK_PRIORITY_AUDIO,
        NULL,
        0  // Core 0
    );

    xTaskCreatePinnedToCore(
        wake_word_task,
        "wake_word",
        TASK_STACK_WAKE,
        NULL,
        TASK_PRIORITY_WAKE,
        NULL,
        1  // Core 1 (dedicated for Porcupine processing)
    );

    xTaskCreatePinnedToCore(
        audio_streaming_task,
        "audio_stream",
        TASK_STACK_STREAM,
        NULL,
        TASK_PRIORITY_STREAM,
        &streaming_task_handle,
        0  // Core 0
    );

    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "System initialized successfully!");
    ESP_LOGI(TAG, "Listening for wake word...");
    ESP_LOGI(TAG, "========================================");

    // Main monitoring loop
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(10000));  // 10 seconds

        // Log system status
        ESP_LOGI(TAG, "Status: %s | Heap: %lu bytes | PSRAM: %lu bytes",
                 state_to_string(state_machine_get()),
                 esp_get_free_heap_size(),
                 heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
    }
}
