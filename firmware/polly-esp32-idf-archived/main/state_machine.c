#include "state_machine.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static const char *TAG = "state_machine";
static app_state_t current_state = STATE_INIT;
static SemaphoreHandle_t state_mutex = NULL;

void state_machine_init(void)
{
    state_mutex = xSemaphoreCreateMutex();
    if (state_mutex == NULL) {
        ESP_LOGE(TAG, "Failed to create state mutex");
        return;
    }
    current_state = STATE_INIT;
    ESP_LOGI(TAG, "State machine initialized");
}

void state_machine_set(app_state_t new_state)
{
    if (state_mutex == NULL) {
        ESP_LOGE(TAG, "State machine not initialized");
        return;
    }

    if (xSemaphoreTake(state_mutex, portMAX_DELAY) == pdTRUE) {
        if (current_state != new_state) {
            ESP_LOGI(TAG, "State transition: %s -> %s",
                     state_to_string(current_state),
                     state_to_string(new_state));
            current_state = new_state;
        }
        xSemaphoreGive(state_mutex);
    }
}

app_state_t state_machine_get(void)
{
    app_state_t state = STATE_INIT;

    if (state_mutex == NULL) {
        ESP_LOGE(TAG, "State machine not initialized");
        return state;
    }

    if (xSemaphoreTake(state_mutex, portMAX_DELAY) == pdTRUE) {
        state = current_state;
        xSemaphoreGive(state_mutex);
    }

    return state;
}

const char* state_to_string(app_state_t state)
{
    switch (state) {
        case STATE_INIT:
            return "INIT";
        case STATE_CONNECTING:
            return "CONNECTING";
        case STATE_IDLE:
            return "IDLE";
        case STATE_WAKE_DETECTED:
            return "WAKE_DETECTED";
        case STATE_PROCESSING:
            return "PROCESSING";
        case STATE_PLAYING:
            return "PLAYING";
        case STATE_ERROR:
            return "ERROR";
        default:
            return "UNKNOWN";
    }
}
