#include "porcupine_manager.h"
#include "config.h"
#include "esp_log.h"
#include <string.h>

static const char *TAG = "porcupine";

// Embedded model references (will be created by CMake)
extern const uint8_t jarvis_ppn_start[] asm("_binary_jarvis_esp_ppn_start");
extern const uint8_t jarvis_ppn_end[]   asm("_binary_jarvis_esp_ppn_end");

esp_err_t porcupine_init(porcupine_ctx_t *ctx)
{
    if (!ctx) {
        ESP_LOGE(TAG, "NULL context provided");
        return ESP_ERR_INVALID_ARG;
    }

    memset(ctx, 0, sizeof(porcupine_ctx_t));

    ctx->access_key = PORCUPINE_ACCESS_KEY;
    ctx->sensitivity = PORCUPINE_SENSITIVITY;
    ctx->model_buffer = jarvis_ppn_start;
    ctx->model_size = jarvis_ppn_end - jarvis_ppn_start;

    ESP_LOGI(TAG, "Initializing Porcupine");
    ESP_LOGI(TAG, "Model size: %d bytes", ctx->model_size);
    ESP_LOGI(TAG, "Sensitivity: %.2f", ctx->sensitivity);

    // Initialize Porcupine
    pv_status_t status = pv_porcupine_init(
        ctx->access_key,
        1,                      // num_keywords (1 wake word)
        &ctx->model_buffer,
        &ctx->sensitivity,
        &ctx->handle
    );

    if (status != PV_STATUS_SUCCESS) {
        ESP_LOGE(TAG, "Porcupine init failed: %d", status);
        return ESP_FAIL;
    }

    // Get Porcupine configuration
    ctx->frame_length = pv_porcupine_frame_length();
    ctx->sample_rate = pv_sample_rate();

    ESP_LOGI(TAG, "Porcupine initialized successfully");
    ESP_LOGI(TAG, "Frame length: %d samples", ctx->frame_length);
    ESP_LOGI(TAG, "Sample rate: %d Hz", ctx->sample_rate);

    // Verify frame size matches our configuration
    if (ctx->frame_length != FRAME_SIZE) {
        ESP_LOGW(TAG, "Frame size mismatch! Expected %d, got %d",
                 FRAME_SIZE, ctx->frame_length);
    }

    if (ctx->sample_rate != SAMPLE_RATE) {
        ESP_LOGW(TAG, "Sample rate mismatch! Expected %d, got %d",
                 SAMPLE_RATE, ctx->sample_rate);
    }

    return ESP_OK;
}

bool porcupine_process_frame(porcupine_ctx_t *ctx, const int16_t *pcm)
{
    if (!ctx || !ctx->handle || !pcm) {
        ESP_LOGE(TAG, "Invalid parameters");
        return false;
    }

    int32_t keyword_index = -1;

    pv_status_t status = pv_porcupine_process(
        ctx->handle,
        pcm,
        &keyword_index
    );

    if (status != PV_STATUS_SUCCESS) {
        ESP_LOGE(TAG, "Porcupine process error: %d", status);
        return false;
    }

    if (keyword_index >= 0) {
        ESP_LOGI(TAG, "*** WAKE WORD DETECTED! (index: %d) ***", keyword_index);
        return true;
    }

    return false;
}

void porcupine_destroy(porcupine_ctx_t *ctx)
{
    if (ctx && ctx->handle) {
        pv_porcupine_delete(ctx->handle);
        ctx->handle = NULL;
        ESP_LOGI(TAG, "Porcupine destroyed");
    }
}
