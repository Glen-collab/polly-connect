/**
 * Polly Connect - ESP32-S3 WebSocket Streaming Firmware
 *
 * Hardware: ESP32-S3-WROOM-1-N16R8 + INMP441 mic + MAX98357A speaker
 *
 * Flow:
 *   1. Boot -> init I2S mic/speaker -> init WiFi
 *   2. Connect WebSocket to server (/api/audio/continuous)
 *   3. Continuously stream mic audio (binary frames) to server
 *   4. Server runs OpenWakeWord -> sends wake_word_detected
 *   5. Server records until silence, runs Whisper STT -> intent -> TTS
 *   6. Server sends response text + audio_chunk frames back
 *   7. ESP32 plays TTS audio, resumes streaming
 *
 * GPIO Wiring (INMP441):
 *   SCK  -> GPIO6
 *   WS   -> GPIO5
 *   SD   -> GPIO4
 *   L/R  -> GND (left channel)
 *   VDD  -> 3.3V
 *   GND  -> GND
 *
 * GPIO Wiring (MAX98357A speaker amp):
 *   BCLK -> GPIO12
 *   LRC  -> GPIO11
 *   DIN  -> GPIO10
 *   VIN  -> 5V
 *   GND  -> GND
 */

#include <stdio.h>
#include <string.h>
#include <math.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "freertos/semphr.h"

#include "esp_log.h"
#include "esp_err.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "nvs_flash.h"

#include "driver/i2s_std.h"
#include "driver/gpio.h"

#include "esp_websocket_client.h"
#include "cJSON.h"
#include "mbedtls/base64.h"

static const char *TAG = "POLLY";

/* --- Configuration --- */

// WiFi
#define WIFI_SSID       "Glen's iPhone"
#define WIFI_PASSWORD   "Wibar33be!!"
#define WIFI_MAX_RETRY  10

// Server
#define SERVER_HOST     "192.168.1.100"
#define SERVER_PORT     8000
#define WS_URI          "ws://" SERVER_HOST ":8000/api/audio/continuous"

// I2S Microphone (INMP441) pins
#define I2S_MIC_SCK     GPIO_NUM_6
#define I2S_MIC_WS      GPIO_NUM_5
#define I2S_MIC_SD      GPIO_NUM_4

// I2S Speaker (MAX98357A) pins
#define I2S_SPK_BCLK    GPIO_NUM_12
#define I2S_SPK_LRC     GPIO_NUM_11
#define I2S_SPK_DIN     GPIO_NUM_10

// Audio
#define SAMPLE_RATE     16000
#define CHUNK_SAMPLES   480         // 30ms chunks for streaming
#define CHUNK_BYTES     (CHUNK_SAMPLES * sizeof(int16_t))  // 960 bytes

// Status LED (built-in on most S3 devkits)
#define LED_PIN         GPIO_NUM_48

// WebSocket
#define WS_BUFFER_SIZE  16384       // 16KB receive buffer
#define WS_RECONNECT_MS 5000

// Response audio buffer (10 seconds max, in PSRAM)
#define RESPONSE_AUDIO_MAX (SAMPLE_RATE * 2 * 10)  // 320000 bytes

/* --- Globals --- */

static i2s_chan_handle_t mic_handle = NULL;
static i2s_chan_handle_t spk_handle = NULL;

static EventGroupHandle_t wifi_event_group;
#define WIFI_CONNECTED_BIT BIT0
static int wifi_retry_count = 0;

static esp_websocket_client_handle_t ws_client = NULL;
static volatile bool ws_connected = false;

// Flags set by WebSocket event handler, consumed by streaming task
static volatile bool wake_detected = false;
static volatile bool streaming_paused = false;

// Response audio accumulation (PSRAM)
static uint8_t *response_audio = NULL;
static size_t response_audio_len = 0;
static SemaphoreHandle_t response_mutex = NULL;
static volatile bool response_complete = false;

// JSON message accumulation (for fragmented WebSocket messages)
static char *msg_accum = NULL;
static size_t msg_accum_len = 0;
#define MSG_ACCUM_SIZE  32768       // 32KB


/* --- LED helpers --- */

static void led_init(void)
{
    gpio_reset_pin(LED_PIN);
    gpio_set_direction(LED_PIN, GPIO_MODE_OUTPUT);
    gpio_set_level(LED_PIN, 0);
}

static void led_set(int on)
{
    gpio_set_level(LED_PIN, on ? 1 : 0);
}


/* --- I2S Microphone --- */

static esp_err_t mic_init(void)
{
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num = 8;
    chan_cfg.dma_frame_num = 480;

    ESP_ERROR_CHECK(i2s_new_channel(&chan_cfg, NULL, &mic_handle));

    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = I2S_MIC_SCK,
            .ws   = I2S_MIC_WS,
            .dout = I2S_GPIO_UNUSED,
            .din  = I2S_MIC_SD,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv   = false,
            },
        },
    };
    std_cfg.slot_cfg.slot_mask = I2S_STD_SLOT_LEFT;

    ESP_ERROR_CHECK(i2s_channel_init_std_mode(mic_handle, &std_cfg));
    ESP_ERROR_CHECK(i2s_channel_enable(mic_handle));

    ESP_LOGI(TAG, "Microphone initialized (INMP441 on GPIO %d/%d/%d)",
             I2S_MIC_SCK, I2S_MIC_WS, I2S_MIC_SD);
    return ESP_OK;
}

static size_t mic_read(int16_t *buffer, size_t samples)
{
    size_t bytes_read = 0;
    esp_err_t ret = i2s_channel_read(mic_handle, buffer, samples * sizeof(int16_t),
                                      &bytes_read, pdMS_TO_TICKS(100));
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Mic read error: %s", esp_err_to_name(ret));
        return 0;
    }
    return bytes_read / sizeof(int16_t);
}


/* --- I2S Speaker --- */

static esp_err_t spk_init(void)
{
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num = 8;
    chan_cfg.dma_frame_num = 480;

    ESP_ERROR_CHECK(i2s_new_channel(&chan_cfg, &spk_handle, NULL));

    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = I2S_SPK_BCLK,
            .ws   = I2S_SPK_LRC,
            .dout = I2S_SPK_DIN,
            .din  = I2S_GPIO_UNUSED,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv   = false,
            },
        },
    };

    ESP_ERROR_CHECK(i2s_channel_init_std_mode(spk_handle, &std_cfg));
    ESP_ERROR_CHECK(i2s_channel_enable(spk_handle));

    ESP_LOGI(TAG, "Speaker initialized (MAX98357A on GPIO %d/%d/%d)",
             I2S_SPK_BCLK, I2S_SPK_LRC, I2S_SPK_DIN);
    return ESP_OK;
}

static void spk_play_tone(int freq_hz, int duration_ms)
{
    int total_samples = SAMPLE_RATE * duration_ms / 1000;
    int16_t *tone = heap_caps_malloc(total_samples * sizeof(int16_t), MALLOC_CAP_SPIRAM);
    if (!tone) return;

    for (int i = 0; i < total_samples; i++) {
        float t = (float)i / SAMPLE_RATE;
        float envelope = 1.0f;
        if (i < 200) envelope = (float)i / 200.0f;
        if (i > total_samples - 200) envelope = (float)(total_samples - i) / 200.0f;
        tone[i] = (int16_t)(sinf(2.0f * M_PI * freq_hz * t) * 8000.0f * envelope);
    }

    size_t written = 0;
    i2s_channel_write(spk_handle, tone, total_samples * sizeof(int16_t), &written, pdMS_TO_TICKS(2000));
    heap_caps_free(tone);
}

static void spk_play_wake_sound(void)
{
    spk_play_tone(800, 80);
    vTaskDelay(pdMS_TO_TICKS(30));
    spk_play_tone(1200, 80);
}

static void spk_play_error_sound(void)
{
    spk_play_tone(200, 300);
}


/* --- WiFi --- */

static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                                int32_t event_id, void *event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        if (wifi_retry_count < WIFI_MAX_RETRY) {
            esp_wifi_connect();
            wifi_retry_count++;
            ESP_LOGI(TAG, "WiFi retry %d/%d", wifi_retry_count, WIFI_MAX_RETRY);
        } else {
            ESP_LOGE(TAG, "WiFi connection failed after %d retries", WIFI_MAX_RETRY);
        }
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
        ESP_LOGI(TAG, "WiFi connected! IP: " IPSTR, IP2STR(&event->ip_info.ip));
        wifi_retry_count = 0;
        xEventGroupSetBits(wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

static void wifi_init(void)
{
    wifi_event_group = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    esp_event_handler_instance_t any_id, got_ip;
    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                         &wifi_event_handler, NULL, &any_id));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                                         &wifi_event_handler, NULL, &got_ip));

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = WIFI_SSID,
            .password = WIFI_PASSWORD,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "Connecting to WiFi '%s'...", WIFI_SSID);

    EventBits_t bits = xEventGroupWaitBits(wifi_event_group, WIFI_CONNECTED_BIT,
                                            pdFALSE, pdFALSE, pdMS_TO_TICKS(15000));
    if (!(bits & WIFI_CONNECTED_BIT)) {
        ESP_LOGW(TAG, "WiFi connection timed out - will keep retrying in background");
    }
}


/* --- WebSocket: process complete JSON message --- */

static void ws_handle_message(const char *json_str, int len)
{
    cJSON *root = cJSON_ParseWithLength(json_str, len);
    if (!root) {
        ESP_LOGW(TAG, "Failed to parse JSON from server");
        return;
    }

    cJSON *event = cJSON_GetObjectItem(root, "event");
    if (!event || !cJSON_IsString(event)) {
        cJSON_Delete(root);
        return;
    }

    const char *evt = event->valuestring;

    if (strcmp(evt, "connected") == 0) {
        cJSON *msg = cJSON_GetObjectItem(root, "message");
        ESP_LOGI(TAG, "Server: %s", msg ? msg->valuestring : "connected");

    } else if (strcmp(evt, "wake_word_detected") == 0) {
        ESP_LOGI(TAG, "*** WAKE WORD DETECTED BY SERVER ***");
        wake_detected = true;

    } else if (strcmp(evt, "response") == 0) {
        cJSON *text = cJSON_GetObjectItem(root, "text");
        cJSON *intent = cJSON_GetObjectItem(root, "intent");
        cJSON *transcription = cJSON_GetObjectItem(root, "transcription");
        ESP_LOGI(TAG, "Response: %s", text ? text->valuestring : "(none)");
        if (transcription && cJSON_IsString(transcription)) {
            ESP_LOGI(TAG, "  Heard: %s", transcription->valuestring);
        }
        if (intent && cJSON_IsString(intent)) {
            ESP_LOGI(TAG, "  Intent: %s", intent->valuestring);
        }
        // Pause mic streaming while we receive/play audio
        streaming_paused = true;

    } else if (strcmp(evt, "audio_chunk") == 0) {
        cJSON *audio = cJSON_GetObjectItem(root, "audio");
        cJSON *final_flag = cJSON_GetObjectItem(root, "final");

        if (audio && cJSON_IsString(audio)) {
            const char *b64 = audio->valuestring;
            size_t b64_len = strlen(b64);

            // Decode base64
            size_t decoded_len = 0;
            // First call to get required size
            mbedtls_base64_decode(NULL, 0, &decoded_len, (const unsigned char *)b64, b64_len);

            if (decoded_len > 0) {
                uint8_t *decoded = heap_caps_malloc(decoded_len, MALLOC_CAP_SPIRAM);
                if (decoded) {
                    size_t actual_len = 0;
                    int ret = mbedtls_base64_decode(decoded, decoded_len, &actual_len,
                                                     (const unsigned char *)b64, b64_len);
                    if (ret == 0 && actual_len > 0) {
                        xSemaphoreTake(response_mutex, portMAX_DELAY);
                        if (response_audio_len + actual_len <= RESPONSE_AUDIO_MAX) {
                            memcpy(response_audio + response_audio_len, decoded, actual_len);
                            response_audio_len += actual_len;
                        } else {
                            ESP_LOGW(TAG, "Response audio buffer full!");
                        }
                        xSemaphoreGive(response_mutex);
                    }
                    heap_caps_free(decoded);
                }
            }
        }

        if (final_flag && cJSON_IsTrue(final_flag)) {
            ESP_LOGI(TAG, "All audio chunks received (%d bytes)", (int)response_audio_len);
            response_complete = true;
        }

    } else if (strcmp(evt, "pong") == 0) {
        // keepalive ack
    } else if (strcmp(evt, "error") == 0) {
        cJSON *msg = cJSON_GetObjectItem(root, "message");
        ESP_LOGE(TAG, "Server error: %s", msg ? msg->valuestring : "unknown");
    }

    cJSON_Delete(root);
}


/* --- WebSocket event handler --- */

static void ws_event_handler(void *arg, esp_event_base_t event_base,
                              int32_t event_id, void *event_data)
{
    esp_websocket_event_data_t *data = (esp_websocket_event_data_t *)event_data;

    switch (event_id) {
        case WEBSOCKET_EVENT_CONNECTED:
            ESP_LOGI(TAG, "WebSocket connected to server");
            ws_connected = true;

            // Send connect event
            {
                const char *connect_msg = "{\"event\":\"connect\",\"device_id\":\"polly001\"}";
                esp_websocket_client_send_text(ws_client, connect_msg,
                                                strlen(connect_msg), pdMS_TO_TICKS(1000));
            }
            break;

        case WEBSOCKET_EVENT_DATA:
            // Only handle text frames (op_code 1)
            if (data->op_code == 0x01 || data->op_code == 0x00) {
                // Accumulate fragments
                if (data->payload_offset == 0) {
                    msg_accum_len = 0;
                }

                size_t space = MSG_ACCUM_SIZE - msg_accum_len - 1;
                size_t copy_len = (data->data_len < (int)space) ? data->data_len : space;
                if (copy_len > 0 && data->data_ptr) {
                    memcpy(msg_accum + msg_accum_len, data->data_ptr, copy_len);
                    msg_accum_len += copy_len;
                    msg_accum[msg_accum_len] = '\0';
                }

                // Complete message?
                if (data->payload_offset + data->data_len >= data->payload_len) {
                    ws_handle_message(msg_accum, msg_accum_len);
                    msg_accum_len = 0;
                }
            }
            break;

        case WEBSOCKET_EVENT_DISCONNECTED:
            ESP_LOGW(TAG, "WebSocket disconnected");
            ws_connected = false;
            break;

        case WEBSOCKET_EVENT_ERROR:
            ESP_LOGE(TAG, "WebSocket error");
            break;

        default:
            break;
    }
}


/* --- WebSocket init --- */

static esp_err_t ws_init(void)
{
    esp_websocket_client_config_t ws_cfg = {
        .uri = WS_URI,
        .buffer_size = WS_BUFFER_SIZE,
        .reconnect_timeout_ms = WS_RECONNECT_MS,
        .task_stack = 8192,
    };

    ws_client = esp_websocket_client_init(&ws_cfg);
    if (!ws_client) {
        ESP_LOGE(TAG, "Failed to init WebSocket client");
        return ESP_FAIL;
    }

    esp_websocket_register_events(ws_client, WEBSOCKET_EVENT_ANY, ws_event_handler, NULL);
    esp_err_t ret = esp_websocket_client_start(ws_client);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start WebSocket client: %s", esp_err_to_name(ret));
        return ret;
    }

    ESP_LOGI(TAG, "WebSocket client started, connecting to %s", WS_URI);
    return ESP_OK;
}


/* --- Play response audio --- */

static void play_response_audio(void)
{
    xSemaphoreTake(response_mutex, portMAX_DELAY);

    if (response_audio_len == 0) {
        xSemaphoreGive(response_mutex);
        return;
    }

    ESP_LOGI(TAG, "Playing response audio (%d bytes)", (int)response_audio_len);

    // Skip WAV header if present
    size_t offset = 0;
    if (response_audio_len > 44 && memcmp(response_audio, "RIFF", 4) == 0) {
        offset = 44;
        ESP_LOGI(TAG, "Skipping WAV header");
    }

    size_t play_len = response_audio_len - offset;
    size_t written = 0;
    i2s_channel_write(spk_handle, response_audio + offset,
                      play_len, &written, pdMS_TO_TICKS(15000));

    ESP_LOGI(TAG, "Playback complete (%d bytes written)", (int)written);

    // Reset buffer
    response_audio_len = 0;
    response_complete = false;

    xSemaphoreGive(response_mutex);
}


/* --- Mic streaming task --- */

static void mic_stream_task(void *arg)
{
    int16_t *audio_chunk = heap_caps_malloc(CHUNK_BYTES, MALLOC_CAP_SPIRAM);
    if (!audio_chunk) {
        ESP_LOGE(TAG, "Failed to allocate mic chunk buffer");
        vTaskDelete(NULL);
        return;
    }

    ESP_LOGI(TAG, "Mic streaming task started");

    uint32_t ping_timer = 0;

    while (1) {
        // Handle wake word detection beep
        if (wake_detected) {
            wake_detected = false;
            led_set(1);
            spk_play_wake_sound();
        }

        // Handle response playback
        if (response_complete) {
            play_response_audio();
            led_set(0);
            streaming_paused = false;
            ESP_LOGI(TAG, "Back to streaming...");
        }

        // Stream mic audio to server (unless paused for playback)
        if (ws_connected && !streaming_paused) {
            size_t samples = mic_read(audio_chunk, CHUNK_SAMPLES);
            if (samples > 0) {
                int ret = esp_websocket_client_send_bin(
                    ws_client,
                    (const char *)audio_chunk,
                    samples * sizeof(int16_t),
                    pdMS_TO_TICKS(500)
                );
                if (ret < 0) {
                    ESP_LOGW(TAG, "WebSocket send failed");
                }
            }
        } else if (streaming_paused) {
            // While paused (waiting for response), still read mic to keep I2S flowing
            // but discard the data
            mic_read(audio_chunk, CHUNK_SAMPLES);
        }

        // Send periodic ping to keep connection alive (every 30 seconds)
        ping_timer++;
        if (ping_timer >= 1000) {  // ~30 seconds at 30ms per loop
            ping_timer = 0;
            if (ws_connected) {
                const char *ping = "{\"event\":\"ping\"}";
                esp_websocket_client_send_text(ws_client, ping, strlen(ping), pdMS_TO_TICKS(1000));
            }
        }

        vTaskDelay(pdMS_TO_TICKS(1));
    }

    heap_caps_free(audio_chunk);
    vTaskDelete(NULL);
}


/* --- App Main --- */

void app_main(void)
{
    ESP_LOGI(TAG, "=== Polly Connect - ESP32-S3 WebSocket Streaming ===");
    ESP_LOGI(TAG, "Free heap: %lu bytes", esp_get_free_heap_size());
    ESP_LOGI(TAG, "Free PSRAM: %lu bytes", heap_caps_get_free_size(MALLOC_CAP_SPIRAM));

    // Init NVS (needed for WiFi)
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    // Init LED
    led_init();
    led_set(1);

    // Init microphone
    ESP_ERROR_CHECK(mic_init());

    // Init speaker
    ESP_ERROR_CHECK(spk_init());

    // Startup sound
    spk_play_tone(1000, 100);
    vTaskDelay(pdMS_TO_TICKS(100));
    spk_play_tone(1500, 100);

    // Init WiFi
    wifi_init();

    // Allocate response audio buffer in PSRAM
    response_audio = heap_caps_malloc(RESPONSE_AUDIO_MAX, MALLOC_CAP_SPIRAM);
    if (!response_audio) {
        ESP_LOGE(TAG, "Failed to allocate response audio buffer!");
        return;
    }
    response_mutex = xSemaphoreCreateMutex();

    // Allocate JSON message accumulation buffer
    msg_accum = heap_caps_malloc(MSG_ACCUM_SIZE, MALLOC_CAP_SPIRAM);
    if (!msg_accum) {
        ESP_LOGE(TAG, "Failed to allocate message buffer!");
        return;
    }
    msg_accum[0] = '\0';

    // Init WebSocket client
    ESP_ERROR_CHECK(ws_init());

    led_set(0);
    ESP_LOGI(TAG, "Setup complete. Streaming audio to server...");

    // Start mic streaming task on core 1 (core 0 handles WiFi/WebSocket)
    xTaskCreatePinnedToCore(mic_stream_task, "mic_stream", 8192, NULL, 5, NULL, 1);
}
