#include "websocket_client.h"
#include "config.h"
#include "esp_websocket_client.h"
#include "esp_log.h"
#include "cJSON.h"
#include <string.h>

static const char *TAG = "websocket";
static esp_websocket_client_handle_t client = NULL;
static websocket_event_callback_t user_callback = NULL;
static bool connected = false;

static void websocket_event_handler(void *handler_args,
                                     esp_event_base_t base,
                                     int32_t event_id,
                                     void *event_data)
{
    esp_websocket_event_data_t *data = (esp_websocket_event_data_t *)event_data;

    switch (event_id) {
        case WEBSOCKET_EVENT_CONNECTED:
            ESP_LOGI(TAG, "WebSocket connected");
            connected = true;

            // Send connect event
            cJSON *msg = cJSON_CreateObject();
            if (msg) {
                cJSON_AddStringToObject(msg, "event", "connect");
                cJSON_AddStringToObject(msg, "device_id", "esp32-s3-001");
                char *json_str = cJSON_PrintUnformatted(msg);
                if (json_str) {
                    esp_websocket_client_send_text(client, json_str,
                                                  strlen(json_str), portMAX_DELAY);
                    free(json_str);
                }
                cJSON_Delete(msg);
            }
            break;

        case WEBSOCKET_EVENT_DISCONNECTED:
            ESP_LOGW(TAG, "WebSocket disconnected");
            connected = false;
            break;

        case WEBSOCKET_EVENT_DATA:
            if (data->op_code == 0x01) {  // Text frame
                ESP_LOGI(TAG, "Received: %.*s", data->data_len,
                         (char *)data->data_ptr);

                if (user_callback) {
                    cJSON *json = cJSON_ParseWithLength(data->data_ptr,
                                                         data->data_len);
                    if (json) {
                        user_callback(json);
                        cJSON_Delete(json);
                    }
                }
            }
            break;

        case WEBSOCKET_EVENT_ERROR:
            ESP_LOGE(TAG, "WebSocket error");
            connected = false;
            break;

        default:
            break;
    }
}

esp_err_t websocket_client_init(const char *uri,
                                 websocket_event_callback_t callback)
{
    if (!uri || !callback) {
        ESP_LOGE(TAG, "Invalid parameters");
        return ESP_ERR_INVALID_ARG;
    }

    user_callback = callback;

    esp_websocket_client_config_t ws_cfg = {
        .uri = uri,
        .task_stack = TASK_STACK_WEBSOCKET,
        .buffer_size = 16384,
        .network_timeout_ms = 10000,
        .ping_interval_sec = 30,
        .disable_auto_reconnect = false,
    };

    client = esp_websocket_client_init(&ws_cfg);
    if (!client) {
        ESP_LOGE(TAG, "Failed to create WebSocket client");
        return ESP_FAIL;
    }

    esp_websocket_register_events(client, WEBSOCKET_EVENT_ANY,
                                   websocket_event_handler, NULL);

    esp_err_t ret = esp_websocket_client_start(client);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start WebSocket client: %s",
                 esp_err_to_name(ret));
        return ret;
    }

    ESP_LOGI(TAG, "WebSocket client started");
    return ESP_OK;
}

esp_err_t websocket_send_wake_detected(void)
{
    if (!connected) {
        ESP_LOGW(TAG, "Not connected, cannot send wake_word_detected");
        return ESP_ERR_INVALID_STATE;
    }

    cJSON *msg = cJSON_CreateObject();
    if (!msg) {
        ESP_LOGE(TAG, "Failed to create JSON object");
        return ESP_ERR_NO_MEM;
    }

    cJSON_AddStringToObject(msg, "event", "wake_word_detected");
    cJSON_AddNumberToObject(msg, "timestamp", esp_timer_get_time() / 1000);

    char *json_str = cJSON_PrintUnformatted(msg);
    if (!json_str) {
        cJSON_Delete(msg);
        return ESP_ERR_NO_MEM;
    }

    int ret = esp_websocket_client_send_text(client, json_str,
                                             strlen(json_str),
                                             pdMS_TO_TICKS(1000));
    free(json_str);
    cJSON_Delete(msg);

    if (ret < 0) {
        ESP_LOGE(TAG, "Failed to send wake_word_detected");
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "Sent wake_word_detected event");
    return ESP_OK;
}

esp_err_t websocket_send_audio(const uint8_t *audio_b64, size_t len)
{
    if (!connected) {
        ESP_LOGD(TAG, "Not connected, cannot send audio");
        return ESP_ERR_INVALID_STATE;
    }

    if (!audio_b64 || len == 0) {
        ESP_LOGE(TAG, "Invalid audio data");
        return ESP_ERR_INVALID_ARG;
    }

    cJSON *msg = cJSON_CreateObject();
    if (!msg) {
        ESP_LOGE(TAG, "Failed to create JSON object");
        return ESP_ERR_NO_MEM;
    }

    cJSON_AddStringToObject(msg, "event", "audio_stream");
    cJSON_AddStringToObject(msg, "data", (const char *)audio_b64);

    char *json_str = cJSON_PrintUnformatted(msg);
    if (!json_str) {
        cJSON_Delete(msg);
        return ESP_ERR_NO_MEM;
    }

    int ret = esp_websocket_client_send_text(client, json_str,
                                             strlen(json_str),
                                             pdMS_TO_TICKS(1000));
    free(json_str);
    cJSON_Delete(msg);

    if (ret < 0) {
        ESP_LOGD(TAG, "Failed to send audio");
        return ESP_FAIL;
    }

    return ESP_OK;
}

esp_err_t websocket_send_command_end(void)
{
    if (!connected) {
        ESP_LOGW(TAG, "Not connected, cannot send command_end");
        return ESP_ERR_INVALID_STATE;
    }

    const char *msg = "{\"event\":\"command_end\"}";
    int ret = esp_websocket_client_send_text(client, msg, strlen(msg),
                                             pdMS_TO_TICKS(1000));

    if (ret < 0) {
        ESP_LOGE(TAG, "Failed to send command_end");
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "Sent command_end event");
    return ESP_OK;
}

bool websocket_is_connected(void)
{
    return connected;
}
