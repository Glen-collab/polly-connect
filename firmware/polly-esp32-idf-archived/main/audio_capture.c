#include "audio_capture.h"
#include "config.h"
#include "esp_log.h"
#include "driver/i2s_std.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include <string.h>

static const char *TAG = "audio_capture";

static i2s_chan_handle_t i2s_rx_handle = NULL;
static QueueHandle_t audio_queue = NULL;
static int16_t *circular_buffer = NULL;
static size_t circular_buffer_idx = 0;
static size_t circular_buffer_frames = 0;

esp_err_t audio_capture_init(QueueHandle_t queue)
{
    audio_queue = queue;

    // Calculate circular buffer size in frames
    circular_buffer_frames = (SAMPLE_RATE * AUDIO_BUFFER_SECS) / FRAME_SIZE;

    // Allocate circular buffer in PSRAM for pre-wake audio
    circular_buffer = heap_caps_malloc(
        circular_buffer_frames * FRAME_SIZE * sizeof(int16_t),
        MALLOC_CAP_SPIRAM
    );
    if (!circular_buffer) {
        ESP_LOGE(TAG, "Failed to allocate circular buffer");
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "Allocated circular buffer: %d frames (%d bytes)",
             circular_buffer_frames,
             circular_buffer_frames * FRAME_SIZE * sizeof(int16_t));

    // Configure I2S channel
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num = 8;
    chan_cfg.dma_frame_num = FRAME_SIZE;

    esp_err_t ret = i2s_new_channel(&chan_cfg, NULL, &i2s_rx_handle);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to create I2S channel: %s", esp_err_to_name(ret));
        free(circular_buffer);
        return ret;
    }

    // Configure I2S standard mode for INMP441
    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
            I2S_DATA_BIT_WIDTH_16BIT,
            I2S_SLOT_MODE_MONO
        ),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = I2S_SCK,
            .ws = I2S_WS,
            .dout = I2S_GPIO_UNUSED,
            .din = I2S_SD,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };

    ret = i2s_channel_init_std_mode(i2s_rx_handle, &std_cfg);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to init I2S standard mode: %s", esp_err_to_name(ret));
        i2s_del_channel(i2s_rx_handle);
        free(circular_buffer);
        return ret;
    }

    // Enable I2S RX channel
    ret = i2s_channel_enable(i2s_rx_handle);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to enable I2S channel: %s", esp_err_to_name(ret));
        i2s_del_channel(i2s_rx_handle);
        free(circular_buffer);
        return ret;
    }

    ESP_LOGI(TAG, "I2S initialized (16kHz, mono, 16-bit)");
    ESP_LOGI(TAG, "GPIO: WS=%d, SD=%d, SCK=%d", I2S_WS, I2S_SD, I2S_SCK);

    return ESP_OK;
}

void audio_capture_task(void *pvParameters)
{
    // Allocate frame buffer in PSRAM
    int16_t *frame = heap_caps_malloc(FRAME_SIZE * sizeof(int16_t),
                                       MALLOC_CAP_SPIRAM);
    if (!frame) {
        ESP_LOGE(TAG, "Failed to allocate frame buffer");
        vTaskDelete(NULL);
        return;
    }

    size_t bytes_read = 0;

    ESP_LOGI(TAG, "Audio capture task started");

    while (1) {
        // Read one frame from I2S
        esp_err_t ret = i2s_channel_read(
            i2s_rx_handle,
            frame,
            FRAME_SIZE_BYTES,
            &bytes_read,
            portMAX_DELAY
        );

        if (ret != ESP_OK) {
            ESP_LOGW(TAG, "I2S read error: %s", esp_err_to_name(ret));
            continue;
        }

        if (bytes_read != FRAME_SIZE_BYTES) {
            ESP_LOGD(TAG, "Incomplete I2S read: %d bytes", bytes_read);
            continue;
        }

        // Store in circular buffer for pre-wake context
        memcpy(&circular_buffer[circular_buffer_idx * FRAME_SIZE],
               frame,
               FRAME_SIZE_BYTES);
        circular_buffer_idx = (circular_buffer_idx + 1) % circular_buffer_frames;

        // Send to wake word task queue
        if (audio_queue) {
            if (xQueueSend(audio_queue, frame, 0) != pdTRUE) {
                // Queue full, drop frame (wake word task is behind)
                ESP_LOGD(TAG, "Audio queue full, dropping frame");
            }
        }
    }

    // Cleanup (should never reach here)
    free(frame);
    vTaskDelete(NULL);
}

int16_t* audio_capture_get_prebuffer(size_t *num_frames)
{
    if (num_frames) {
        *num_frames = circular_buffer_frames;
    }
    return circular_buffer;
}

size_t audio_capture_get_buffer_index(void)
{
    return circular_buffer_idx;
}
