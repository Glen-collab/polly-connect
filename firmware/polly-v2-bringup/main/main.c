/*
 * Polly v2 board bring-up test  (Paul's canonical board) — robust/LED-first.
 *
 * LED comes up FIRST and stays lit, so the board itself is the debug output:
 *   - boot:  solid WHITE for ~1.5s  -> "I booted and the LED works"
 *   - then:  color sweep            -> "app loop is running"
 * Audio + mic init are non-fatal (a failure logs but never crashes the app).
 *
 * Pin map verified against hardware/polly-board/Polly_v2.kicad_sch + netlist.ipc:
 *   amp  MAX98357: DIN=10 LRCLK=11 BCLK=12, SD_MODE(enable)=13
 *   mic  ICS-43434: SD=4 WS=5 SCK=6
 *   LED  SK6812:    DATA=48
 */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "driver/i2s_std.h"
#include "esp_log.h"
#include "led_strip.h"

static const char *TAG = "polly_bringup";
#define PI_F 3.14159265f

#define AMP_SD_MODE GPIO_NUM_13
#define AMP_BCLK    GPIO_NUM_12
#define AMP_LRCLK   GPIO_NUM_11
#define AMP_DIN     GPIO_NUM_10
#define MIC_SCK     GPIO_NUM_6
#define MIC_WS      GPIO_NUM_5
#define MIC_SD      GPIO_NUM_4
#define LED_GPIO    GPIO_NUM_48
#define LED_NUM     3
#define SAMPLE_RATE 16000
#define TONE_HZ     660

static i2s_chan_handle_t tx_chan = NULL;
static led_strip_handle_t strip = NULL;

static void amp_enable(void)
{
    gpio_config_t io = { .pin_bit_mask = 1ULL << AMP_SD_MODE, .mode = GPIO_MODE_OUTPUT };
    gpio_config(&io);
    gpio_set_level(AMP_SD_MODE, 1);
    ESP_LOGI(TAG, "amp SD_MODE (GPIO13) HIGH");
}

static esp_err_t led_init(void)
{
    led_strip_config_t sc = {
        .strip_gpio_num = LED_GPIO,
        .max_leds = LED_NUM,
        .led_model = LED_MODEL_SK6812,
        .led_pixel_format = LED_PIXEL_FORMAT_GRB,
        .flags = { .invert_out = false },
    };
    led_strip_rmt_config_t rc = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 10 * 1000 * 1000,
        .flags = { .with_dma = false },
    };
    esp_err_t err = led_strip_new_rmt_device(&sc, &rc, &strip);
    ESP_LOGI(TAG, "led_strip init: %s", esp_err_to_name(err));
    return err;
}

static void led_set_all(uint8_t r, uint8_t g, uint8_t b)
{
    if (!strip) return;
    for (int i = 0; i < LED_NUM; i++) led_strip_set_pixel(strip, i, r, g, b);
    led_strip_refresh(strip);
}

static void led_task(void *arg)
{
    const uint8_t colors[][3] = {
        {120, 0, 0}, {0, 120, 0}, {0, 0, 120},
        {120, 120, 0}, {0, 120, 120}, {120, 0, 120},
    };
    int c = 0;
    while (1) {
        led_set_all(colors[c][0], colors[c][1], colors[c][2]);
        c = (c + 1) % 6;
        vTaskDelay(pdMS_TO_TICKS(400));
    }
}

static esp_err_t speaker_init(void)
{
    i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    esp_err_t err = i2s_new_channel(&cc, &tx_chan, NULL);
    if (err != ESP_OK) { ESP_LOGE(TAG, "i2s tx chan: %s", esp_err_to_name(err)); return err; }
    i2s_std_config_t std = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = { .mclk = I2S_GPIO_UNUSED, .bclk = AMP_BCLK, .ws = AMP_LRCLK,
                      .dout = AMP_DIN, .din = I2S_GPIO_UNUSED, .invert_flags = { 0 } },
    };
    err = i2s_channel_init_std_mode(tx_chan, &std);
    if (err != ESP_OK) { ESP_LOGE(TAG, "i2s tx init: %s", esp_err_to_name(err)); return err; }
    err = i2s_channel_enable(tx_chan);
    ESP_LOGI(TAG, "speaker init: %s", esp_err_to_name(err));
    return err;
}

static void speaker_task(void *arg)
{
    const int frames = 256;
    int16_t buf[frames * 2];
    float phase = 0.0f, step = 2.0f * PI_F * TONE_HZ / SAMPLE_RATE;
    bool on = true;
    int ticks = 0;
    size_t wrote;
    while (1) {
        for (int i = 0; i < frames; i++) {
            int16_t s = on ? (int16_t)(sinf(phase) * 6000.0f) : 0;
            phase += step;
            if (phase > 2.0f * PI_F) phase -= 2.0f * PI_F;
            buf[2 * i] = s; buf[2 * i + 1] = s;
        }
        if (i2s_channel_write(tx_chan, buf, sizeof(buf), &wrote, portMAX_DELAY) != ESP_OK)
            vTaskDelay(pdMS_TO_TICKS(100));
        if (++ticks >= (SAMPLE_RATE / frames) / 2) { ticks = 0; on = !on; }
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "==== Polly v2 bring-up (LED-first) ====");

    /* LED first — visible proof the board booted */
    if (led_init() == ESP_OK) {
        led_set_all(120, 120, 120);          /* solid white ~1.5s */
        vTaskDelay(pdMS_TO_TICKS(1500));
        xTaskCreate(led_task, "led", 4096, NULL, 6, NULL);
    } else {
        ESP_LOGE(TAG, "LED init FAILED — check GPIO48 / data level");
    }

    /* Audio — non-fatal */
    amp_enable();
    if (speaker_init() == ESP_OK)
        xTaskCreate(speaker_task, "spk", 4096, NULL, 5, NULL);
    else
        ESP_LOGE(TAG, "speaker disabled (init failed)");

    ESP_LOGI(TAG, "app_main done; LED should be sweeping colors");
}
