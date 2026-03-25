/**
 * Polly Connect - Waveshare ESP32-S3-AUDIO-Board Firmware
 *
 * Hardware: Waveshare ESP32-S3R8, ES8311 DAC, ES7210 ADC, TCA9555 expander
 *
 * Same WebSocket streaming protocol as the breadboard firmware:
 *   1. Boot -> init I2C -> init codecs -> init I2S -> init WiFi
 *   2. Connect WebSocket to server (/api/audio/continuous)
 *   3. Continuously stream mic audio (binary frames) to server
 *   4. Server runs VAD + wake word -> sends wake_word_detected
 *   5. Server records until silence, runs STT -> intent -> TTS
 *   6. Server sends response text + audio_chunk frames back
 *   7. ESP32 plays TTS audio, resumes streaming
 *
 * Pin Map (Waveshare ESP32-S3-AUDIO-Board):
 *   I2C:  SDA=GPIO1, SCL=GPIO2
 *   I2S:  MCLK=GPIO0, BCLK=GPIO3, WS=GPIO4, DOUT=GPIO5, DIN=GPIO6
 *   LED:  GPIO48 (WS2812 RGB, used as simple on/off)
 *
 * Codec I2C Addresses:
 *   ES8311 (DAC/speaker) = 0x18
 *   ES7210 (ADC/mic)     = 0x40
 *   TCA9555 (expander)   = 0x20
 */

#include <stdio.h>
#include <string.h>
#include <math.h>
#include <inttypes.h>

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
#include "driver/i2c.h"
#include "driver/gpio.h"

#include "esp_websocket_client.h"
#include "cJSON.h"
#include "mbedtls/base64.h"
#include "esp_http_server.h"
#include "esp_netif.h"
#include "lwip/sockets.h"
#include "esp_ota_ops.h"
#include "esp_http_client.h"
#include "esp_app_format.h"

static const char *TAG = "POLLY-WS";

/* --- Configuration --- */

// Firmware version (for OTA updates)
#define FW_VERSION      "1.0.4"
#define FW_VARIANT      "waveshare"

// WiFi
#define WIFI_SSID       "SpectrumSetup-73"
#define WIFI_PASSWORD   "orangegate448"
#define WIFI_MAX_RETRY  10
#define WIFI_MAX_SAVED  5   // Max remembered WiFi networks

// Server
#define SERVER_HOST     "polly-connect.com"
#define SERVER_PORT     8000
#define WS_URI          "ws://" SERVER_HOST ":8000/api/audio/continuous"

// Device identity — loaded from NVS at boot (set during claim code provisioning)
// Fallback defines used only if NVS has no credentials (legacy/dev devices)
#define DEVICE_ID_FALLBACK       "polly-waveshare"
#define DEVICE_API_KEY_FALLBACK  "qtde_XgbmZ2jExSBRH0jtsKIgjMkcEwl-BoabvVj7GE"

static char g_device_id[64] = {0};
static char g_api_key[64] = {0};

// I2C bus (controls ES8311, ES7210, TCA9555)
#define I2C_SDA         GPIO_NUM_11
#define I2C_SCL         GPIO_NUM_10
#define I2C_PORT        I2C_NUM_0
#define I2C_FREQ_HZ     400000

// I2S shared bus (audio data to/from both codecs)
#define I2S_MCLK        GPIO_NUM_12
#define I2S_BCLK        GPIO_NUM_13
#define I2S_WS          GPIO_NUM_14
#define I2S_DOUT        GPIO_NUM_16  // ESP32 TX -> ES8311 (speaker)
#define I2S_DIN         GPIO_NUM_15  // ES7210 TX -> ESP32 (mic)

// Codec I2C addresses
#define ES8311_ADDR     0x18
#define ES7210_ADDR     0x40
#define TCA9555_ADDR    0x20

// TCA9555 port bits (from xiaozhi-esp32 working implementation)
// Port 0: bit 0 = LCD reset, bit 1 = touchpad reset, bit 5 = camera reset, bit 6 = camera power
// Port 1: bit 0 (pin 8) = speaker amplifier enable
// Port 1: bit 1 (pin 9) = K1/+ button (story record toggle)
// Port 1: bit 2 (pin 10) = K2/SET button
// Port 1: bit 3 (pin 11) = K3 button
#define TCA_PA_PIN      0x01    // Port 1 bit 0: speaker amplifier enable
#define TCA_KEY1_BIT    0x02    // Port 1 bit 1: K1/+ button
#define TCA_KEY2_BIT    0x04    // Port 1 bit 2: K2/SET button
#define TCA_KEY3_BIT    0x08    // Port 1 bit 3: K3 button

// Status LED (WS2812 RGB on GPIO48, driven as simple GPIO)
#define LED_PIN         GPIO_NUM_48

// Audio
#define SAMPLE_RATE     16000
#define CHUNK_SAMPLES   480         // 30ms chunks for streaming
#define CHUNK_BYTES     (CHUNK_SAMPLES * sizeof(int16_t))  // 960 bytes

// WebSocket
#define WS_BUFFER_SIZE  8192
#define WS_RECONNECT_MS 5000

// Response audio buffer (30 seconds max, in PSRAM)
#define RESPONSE_AUDIO_MAX (SAMPLE_RATE * 2 * 30)  // 960000 bytes


/* --- Globals --- */

static i2s_chan_handle_t mic_handle = NULL;
static i2s_chan_handle_t spk_handle = NULL;

static EventGroupHandle_t wifi_event_group;
#define WIFI_CONNECTED_BIT BIT0
static int wifi_retry_count = 0;

static esp_websocket_client_handle_t ws_client = NULL;
static volatile bool ws_connected = false;
static volatile bool ota_in_progress = false;

// Flags set by WebSocket event handler, consumed by streaming task
static volatile bool wake_detected = false;
static volatile bool streaming_paused = false;

// Story recording state
static volatile bool story_recording = false;
static volatile bool story_button_pressed = false;  // set by button poll task

// Response audio accumulation (PSRAM)
static uint8_t *response_audio = NULL;
static size_t response_audio_len = 0;
static SemaphoreHandle_t response_mutex = NULL;
static volatile bool response_complete = false;

// JSON message accumulation (for fragmented WebSocket messages)
static char *msg_accum = NULL;
static size_t msg_accum_len = 0;
#define MSG_ACCUM_SIZE  32768       // 32KB


/* --- I2C helpers --- */

static esp_err_t i2c_init(void)
{
    i2c_config_t conf = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = I2C_SDA,
        .scl_io_num = I2C_SCL,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = I2C_FREQ_HZ,
    };
    ESP_ERROR_CHECK(i2c_param_config(I2C_PORT, &conf));
    ESP_ERROR_CHECK(i2c_driver_install(I2C_PORT, I2C_MODE_MASTER, 0, 0, 0));
    ESP_LOGI(TAG, "I2C initialized (SDA=%d, SCL=%d)", I2C_SDA, I2C_SCL);
    return ESP_OK;
}

static esp_err_t i2c_write_reg(uint8_t dev_addr, uint8_t reg, uint8_t val)
{
    uint8_t buf[2] = {reg, val};
    return i2c_master_write_to_device(I2C_PORT, dev_addr, buf, 2, pdMS_TO_TICKS(100));
}

static uint8_t i2c_read_reg(uint8_t dev_addr, uint8_t reg)
{
    uint8_t val = 0;
    i2c_master_write_read_device(I2C_PORT, dev_addr, &reg, 1, &val, 1, pdMS_TO_TICKS(100));
    return val;
}


/* --- TCA9555 Port Expander --- */

static void tca9555_init(void)
{
    // Port 0: bits 0,1,5,6 as output (LCD reset, touch reset, camera reset/power)
    // Port 1: bit 0 as output (speaker amp enable)
    i2c_write_reg(TCA9555_ADDR, 0x06, 0x00);  // direction port 0: all output
    i2c_write_reg(TCA9555_ADDR, 0x07, 0xFE);  // direction port 1: bit 0 output, rest input
    i2c_write_reg(TCA9555_ADDR, 0x02, 0x03);  // port 0: bits 0,1 high (LCD/touch reset)
    i2c_write_reg(TCA9555_ADDR, 0x03, 0x00);  // port 1: amp off initially
    ESP_LOGI(TAG, "TCA9555 port expander initialized");
}

static void tca9555_amp_enable(bool on)
{
    // Speaker amp is on port 1, bit 0 (TCA9555 pin 8)
    // Preserve other output bits while toggling amp
    i2c_write_reg(TCA9555_ADDR, 0x03, on ? TCA_PA_PIN : 0x00);
}

static bool tca9555_read_key1(void)
{
    // Read port 1 input register (0x01), check bit 1 (K1/+ button)
    // Active low: button pressed = bit is 0
    uint8_t port1 = i2c_read_reg(TCA9555_ADDR, 0x01);
    return !(port1 & TCA_KEY1_BIT);
}

/* --- Story Button Polling Task --- */

static void story_button_task(void *arg)
{
    bool last_state = false;
    TickType_t last_press_tick = 0;
    const TickType_t debounce_ticks = pdMS_TO_TICKS(300);

    ESP_LOGI(TAG, "Story button task started (K1/+ via TCA9555)");

    while (1) {
        bool pressed = tca9555_read_key1();

        // Detect rising edge (not pressed -> pressed) with debounce
        if (pressed && !last_state) {
            TickType_t now = xTaskGetTickCount();
            if ((now - last_press_tick) > debounce_ticks) {
                last_press_tick = now;
                story_button_pressed = true;
                ESP_LOGI(TAG, "K1/+ button pressed (story toggle)");
            }
        }
        last_state = pressed;

        vTaskDelay(pdMS_TO_TICKS(50));  // poll every 50ms
    }
}


/* --- ES8311 DAC (speaker codec) --- */

static void es8311_init(void)
{
    // ===== Official Espressif ES8311 init sequence (from esp-bsp) =====

    // Reset
    i2c_write_reg(ES8311_ADDR, 0x00, 0x1F);  // RESET_REG00
    vTaskDelay(pdMS_TO_TICKS(20));
    i2c_write_reg(ES8311_ADDR, 0x00, 0x00);  // Clear reset
    i2c_write_reg(ES8311_ADDR, 0x00, 0x80);  // Power-on command

    // Clock configuration for 16kHz, MCLK = 256*fs = 4.096MHz
    i2c_write_reg(ES8311_ADDR, 0x01, 0x3F);  // CLK_MANAGER_REG01: MCLK from pin, all clocks on
    i2c_write_reg(ES8311_ADDR, 0x02, 0x00);  // CLK_MANAGER_REG02: MCLK/1
    i2c_write_reg(ES8311_ADDR, 0x03, 0x10);  // CLK_MANAGER_REG03: ADC/DAC osr
    i2c_write_reg(ES8311_ADDR, 0x04, 0x10);  // CLK_MANAGER_REG04: LRCK high
    i2c_write_reg(ES8311_ADDR, 0x05, 0x00);  // CLK_MANAGER_REG05: LRCK low
    i2c_write_reg(ES8311_ADDR, 0x06, 0x03);  // CLK_MANAGER_REG06: BCLK divider
    i2c_write_reg(ES8311_ADDR, 0x07, 0x00);  // CLK_MANAGER_REG07: slave mode
    i2c_write_reg(ES8311_ADDR, 0x08, 0xFF);  // CLK_MANAGER_REG08: slow clk enable

    // I2S format: slave, 16-bit, I2S standard
    i2c_write_reg(ES8311_ADDR, 0x09, 0x0C);  // SDP_IN_REG09:  16-bit I2S
    i2c_write_reg(ES8311_ADDR, 0x0A, 0x0C);  // SDP_OUT_REG0A: 16-bit I2S

    // Power up analog circuitry
    i2c_write_reg(ES8311_ADDR, 0x0D, 0x01);  // SYSTEM_REG0D: power up analog
    i2c_write_reg(ES8311_ADDR, 0x0E, 0x02);  // SYSTEM_REG0E: enable analog PGA, ADC modulator
    i2c_write_reg(ES8311_ADDR, 0x12, 0x00);  // SYSTEM_REG12: power up DAC
    i2c_write_reg(ES8311_ADDR, 0x13, 0x10);  // SYSTEM_REG13: enable output to HP drive

    // ADC config
    i2c_write_reg(ES8311_ADDR, 0x1C, 0x6A);  // ADC_REG1C: equalizer bypass, cancel DC offset

    // DAC config
    i2c_write_reg(ES8311_ADDR, 0x37, 0x08);  // DAC_REG37: bypass DAC equalizer
    i2c_write_reg(ES8311_ADDR, 0x32, 0xBF);  // DAC_REG32: volume = 0dB (0xBF)

    // GPIO & analog output
    i2c_write_reg(ES8311_ADDR, 0x44, 0x08);  // GPIO_REG44
    i2c_write_reg(ES8311_ADDR, 0x45, 0x00);  // GP_REG45: analog outputs on

    // Verify
    uint8_t check = i2c_read_reg(ES8311_ADDR, 0x00);
    ESP_LOGI(TAG, "ES8311 DAC initialized (reg00 readback: 0x%02X)", check);
}


/* --- ES7210 ADC (dual mic codec) --- */

static void i2c_scan(void)
{
    ESP_LOGI(TAG, "I2C bus scan on SDA=%d SCL=%d:", I2C_SDA, I2C_SCL);
    int found = 0;
    for (uint8_t addr = 0x08; addr < 0x78; addr++) {
        // Use write with 0 data bytes to probe — more reliable than read
        i2c_cmd_handle_t cmd = i2c_cmd_link_create();
        i2c_master_start(cmd);
        i2c_master_write_byte(cmd, (addr << 1) | I2C_MASTER_WRITE, true);
        i2c_master_stop(cmd);
        esp_err_t ret = i2c_master_cmd_begin(I2C_PORT, cmd, pdMS_TO_TICKS(50));
        i2c_cmd_link_delete(cmd);
        if (ret == ESP_OK) {
            ESP_LOGI(TAG, "  Found device at 0x%02X", addr);
            found++;
        }
    }
    if (found == 0) {
        ESP_LOGW(TAG, "  No I2C devices found! Check SDA/SCL pins.");
    }
}

static void es7210_init(void)
{
    // ===== Official Espressif ES7210 init sequence (from esp-bsp) =====

    // Software reset
    i2c_write_reg(ES7210_ADDR, 0x00, 0xFF);  // RESET_REG00
    vTaskDelay(pdMS_TO_TICKS(20));
    i2c_write_reg(ES7210_ADDR, 0x00, 0x32);  // RESET_REG00: normal operation
    vTaskDelay(pdMS_TO_TICKS(10));

    // Set initialization time when device powers up
    i2c_write_reg(ES7210_ADDR, 0x09, 0x30);  // TIME_CONTROL0_REG09
    i2c_write_reg(ES7210_ADDR, 0x0A, 0x30);  // TIME_CONTROL1_REG0A

    // Configure HPF for ADC1-4
    i2c_write_reg(ES7210_ADDR, 0x23, 0x2A);  // ADC12_HPF1_REG23
    i2c_write_reg(ES7210_ADDR, 0x22, 0x0A);  // ADC12_HPF2_REG22
    i2c_write_reg(ES7210_ADDR, 0x21, 0x2A);  // ADC34_HPF1_REG21
    i2c_write_reg(ES7210_ADDR, 0x20, 0x0A);  // ADC34_HPF2_REG20

    // I2S format: standard I2S, 16-bit
    // SDP_INTERFACE1_REG11: I2S_FMT_I2S(0x00) | 16bit(0x60) = 0x60
    i2c_write_reg(ES7210_ADDR, 0x11, 0x60);
    // SDP_INTERFACE2_REG12: TDM disabled = 0x00
    i2c_write_reg(ES7210_ADDR, 0x12, 0x00);

    // Configure analog power and VMID voltage
    i2c_write_reg(ES7210_ADDR, 0x40, 0xC3);  // ANALOG_REG40

    // Set MIC1-4 bias to 2.87V
    i2c_write_reg(ES7210_ADDR, 0x41, 0x70);  // MIC12_BIAS_REG41
    i2c_write_reg(ES7210_ADDR, 0x42, 0x70);  // MIC34_BIAS_REG42

    // Set MIC1-4 gain to 30dB (gain=10, 0x10 flag = power on)
    i2c_write_reg(ES7210_ADDR, 0x43, 0x1A);  // MIC1_GAIN_REG43: 10 | 0x10
    i2c_write_reg(ES7210_ADDR, 0x44, 0x1A);  // MIC2_GAIN_REG44: 10 | 0x10
    i2c_write_reg(ES7210_ADDR, 0x45, 0x1A);  // MIC3_GAIN_REG45
    i2c_write_reg(ES7210_ADDR, 0x46, 0x1A);  // MIC4_GAIN_REG46

    // Power on MIC1-4
    i2c_write_reg(ES7210_ADDR, 0x47, 0x08);  // MIC1_POWER_REG47
    i2c_write_reg(ES7210_ADDR, 0x48, 0x08);  // MIC2_POWER_REG48
    i2c_write_reg(ES7210_ADDR, 0x49, 0x08);  // MIC3_POWER_REG49
    i2c_write_reg(ES7210_ADDR, 0x4A, 0x08);  // MIC4_POWER_REG4A

    // Set ADC sample rate for 16kHz with MCLK=4.096MHz (256*16000)
    // From coefficient table: osr=0x20, adc_div=1, doubler=1, dll=1, lrck_h=0x01, lrck_l=0x00
    i2c_write_reg(ES7210_ADDR, 0x07, 0x20);  // OSR_REG07
    i2c_write_reg(ES7210_ADDR, 0x02, 0xC1);  // MAINCLK_REG02: adc_div=1 | doubler<<6 | dll<<7
    i2c_write_reg(ES7210_ADDR, 0x04, 0x01);  // LRCK_DIVH_REG04
    i2c_write_reg(ES7210_ADDR, 0x05, 0x00);  // LRCK_DIVL_REG05

    // Power down DLL
    i2c_write_reg(ES7210_ADDR, 0x06, 0x04);  // POWER_DOWN_REG06

    // Power on MIC1-4 bias & ADC1-4 & PGA1-4
    i2c_write_reg(ES7210_ADDR, 0x4B, 0x0F);  // MIC12_POWER_REG4B
    i2c_write_reg(ES7210_ADDR, 0x4C, 0x0F);  // MIC34_POWER_REG4C

    // Enable device (final activation)
    i2c_write_reg(ES7210_ADDR, 0x00, 0x71);
    i2c_write_reg(ES7210_ADDR, 0x00, 0x41);

    // Verify
    uint8_t check = i2c_read_reg(ES7210_ADDR, 0x00);
    ESP_LOGI(TAG, "ES7210 ADC initialized (reg00 readback: 0x%02X, expect 0x41)", check);
}


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


/* --- I2S init (full-duplex on single port) --- */

static esp_err_t audio_i2s_init(void)
{
    // Both mic (RX) and speaker (TX) share I2S_NUM_0 in full-duplex mode
    // They share MCLK, BCLK, WS but have separate data pins (DIN, DOUT)
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num = 8;
    chan_cfg.dma_frame_num = 480;

    // Create both TX and RX channels on the same I2S port (full-duplex)
    ESP_ERROR_CHECK(i2s_new_channel(&chan_cfg, &spk_handle, &mic_handle));

    // RX config (mic from ES7210)
    i2s_std_config_t rx_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = {
            .mclk = I2S_MCLK,
            .bclk = I2S_BCLK,
            .ws   = I2S_WS,
            .dout = I2S_GPIO_UNUSED,
            .din  = I2S_DIN,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv   = false,
            },
        },
    };
    rx_cfg.slot_cfg.slot_mask = I2S_STD_SLOT_LEFT;  // Mono: left mic channel
    ESP_ERROR_CHECK(i2s_channel_init_std_mode(mic_handle, &rx_cfg));

    // TX config (speaker to ES8311)
    i2s_std_config_t tx_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = {
            .mclk = I2S_MCLK,
            .bclk = I2S_BCLK,
            .ws   = I2S_WS,
            .dout = I2S_DOUT,
            .din  = I2S_GPIO_UNUSED,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv   = false,
            },
        },
    };
    ESP_ERROR_CHECK(i2s_channel_init_std_mode(spk_handle, &tx_cfg));

    // Enable both channels
    ESP_ERROR_CHECK(i2s_channel_enable(mic_handle));
    ESP_ERROR_CHECK(i2s_channel_enable(spk_handle));

    ESP_LOGI(TAG, "I2S initialized (full-duplex, MCLK=%d, BCLK=%d, WS=%d, DOUT=%d, DIN=%d)",
             I2S_MCLK, I2S_BCLK, I2S_WS, I2S_DOUT, I2S_DIN);
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


/* --- WiFi --- */

// Provisioning state
static SemaphoreHandle_t provision_done_sem = NULL;
static esp_netif_t *sta_netif = NULL;
static esp_netif_t *ap_netif = NULL;
static httpd_handle_t portal_server = NULL;
static TaskHandle_t dns_task_handle = NULL;
// --- NVS helpers (multi-network) ---

typedef struct {
    char ssid[33];
    char pass[65];
} wifi_cred_t;

static int wifi_nvs_load_all(wifi_cred_t *creds, int max_creds)
{
    nvs_handle_t h;
    if (nvs_open("wifi_cfg", NVS_READONLY, &h) != ESP_OK) return 0;
    uint8_t count = 0;
    nvs_get_u8(h, "count", &count);
    if (count > max_creds) count = max_creds;
    int loaded = 0;
    for (int i = 0; i < count; i++) {
        char key_s[16], key_p[16];
        snprintf(key_s, sizeof(key_s), "ssid%d", i);
        snprintf(key_p, sizeof(key_p), "pass%d", i);
        size_t s_len = sizeof(creds[loaded].ssid);
        size_t p_len = sizeof(creds[loaded].pass);
        esp_err_t r1 = nvs_get_str(h, key_s, creds[loaded].ssid, &s_len);
        esp_err_t r2 = nvs_get_str(h, key_p, creds[loaded].pass, &p_len);
        if (r1 == ESP_OK && r2 == ESP_OK && strlen(creds[loaded].ssid) > 0) {
            ESP_LOGI(TAG, "NVS slot %d: '%s'", i, creds[loaded].ssid);
            loaded++;
        }
    }
    nvs_close(h);
    return loaded;
}

static esp_err_t wifi_nvs_save(const char *ssid, const char *pass)
{
    // Load existing credentials
    wifi_cred_t creds[WIFI_MAX_SAVED] = {0};
    int count = wifi_nvs_load_all(creds, WIFI_MAX_SAVED);

    // Check if this SSID already exists — update password if so
    for (int i = 0; i < count; i++) {
        if (strcmp(creds[i].ssid, ssid) == 0) {
            strncpy(creds[i].pass, pass, sizeof(creds[i].pass) - 1);
            ESP_LOGI(TAG, "Updated password for '%s' (slot %d)", ssid, i);
            goto save;
        }
    }

    // New network — add to list
    if (count < WIFI_MAX_SAVED) {
        strncpy(creds[count].ssid, ssid, sizeof(creds[count].ssid) - 1);
        strncpy(creds[count].pass, pass, sizeof(creds[count].pass) - 1);
        count++;
        ESP_LOGI(TAG, "Added '%s' (slot %d)", ssid, count - 1);
    } else {
        // Full — replace oldest (slot 0), shift others down
        for (int i = 0; i < WIFI_MAX_SAVED - 1; i++) {
            creds[i] = creds[i + 1];
        }
        strncpy(creds[WIFI_MAX_SAVED - 1].ssid, ssid, sizeof(creds[WIFI_MAX_SAVED - 1].ssid) - 1);
        strncpy(creds[WIFI_MAX_SAVED - 1].pass, pass, sizeof(creds[WIFI_MAX_SAVED - 1].pass) - 1);
        ESP_LOGI(TAG, "Replaced oldest, added '%s' (slot %d)", ssid, WIFI_MAX_SAVED - 1);
    }

save:;
    nvs_handle_t h;
    ESP_ERROR_CHECK(nvs_open("wifi_cfg", NVS_READWRITE, &h));
    nvs_set_u8(h, "count", (uint8_t)count);
    for (int i = 0; i < count; i++) {
        char key_s[16], key_p[16];
        snprintf(key_s, sizeof(key_s), "ssid%d", i);
        snprintf(key_p, sizeof(key_p), "pass%d", i);
        nvs_set_str(h, key_s, creds[i].ssid);
        nvs_set_str(h, key_p, creds[i].pass);
    }
    nvs_commit(h);
    nvs_close(h);
    ESP_LOGI(TAG, "Saved %d WiFi network(s) to NVS", count);
    return ESP_OK;
}

static esp_err_t wifi_nvs_clear(void)
{
    nvs_handle_t h;
    ESP_ERROR_CHECK(nvs_open("wifi_cfg", NVS_READWRITE, &h));
    nvs_erase_all(h);
    nvs_commit(h);
    nvs_close(h);
    ESP_LOGI(TAG, "WiFi credentials cleared from NVS");
    return ESP_OK;
}

// --- Device credential NVS helpers ---

static bool device_nvs_load(char *device_id, size_t id_size, char *api_key, size_t key_size)
{
    nvs_handle_t h;
    if (nvs_open("dev_cfg", NVS_READONLY, &h) != ESP_OK) return false;
    esp_err_t r1 = nvs_get_str(h, "dev_id", device_id, &id_size);
    esp_err_t r2 = nvs_get_str(h, "api_key", api_key, &key_size);
    nvs_close(h);
    if (r1 == ESP_OK && r2 == ESP_OK && strlen(device_id) > 0 && strlen(api_key) > 0) {
        ESP_LOGI(TAG, "Device credentials loaded from NVS: %s", device_id);
        return true;
    }
    return false;
}

static esp_err_t device_nvs_save(const char *device_id, const char *api_key)
{
    nvs_handle_t h;
    ESP_ERROR_CHECK(nvs_open("dev_cfg", NVS_READWRITE, &h));
    nvs_set_str(h, "dev_id", device_id);
    nvs_set_str(h, "api_key", api_key);
    nvs_commit(h);
    nvs_close(h);
    ESP_LOGI(TAG, "Device credentials saved to NVS: %s", device_id);
    return ESP_OK;
}

static esp_err_t device_nvs_save_claim_code(const char *claim_code)
{
    nvs_handle_t h;
    ESP_ERROR_CHECK(nvs_open("dev_cfg", NVS_READWRITE, &h));
    nvs_set_str(h, "claim", claim_code);
    nvs_commit(h);
    nvs_close(h);
    ESP_LOGI(TAG, "Claim code saved to NVS");
    return ESP_OK;
}

static bool device_nvs_load_claim_code(char *claim_code, size_t size)
{
    nvs_handle_t h;
    if (nvs_open("dev_cfg", NVS_READONLY, &h) != ESP_OK) return false;
    esp_err_t r = nvs_get_str(h, "claim", claim_code, &size);
    nvs_close(h);
    return (r == ESP_OK && strlen(claim_code) > 0);
}

static void device_nvs_clear_claim_code(void)
{
    nvs_handle_t h;
    if (nvs_open("dev_cfg", NVS_READWRITE, &h) != ESP_OK) return;
    nvs_erase_key(h, "claim");
    nvs_commit(h);
    nvs_close(h);
}

// --- STA connection ---

static esp_event_handler_instance_t sta_any_id_handle, sta_got_ip_handle;
static bool sta_initialized = false;

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

static void wifi_sta_init(void)
{
    if (sta_initialized) return;
    wifi_event_group = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    sta_netif = esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                         &wifi_event_handler, NULL, &sta_any_id_handle));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                                         &wifi_event_handler, NULL, &sta_got_ip_handle));
    sta_initialized = true;
}

static void wifi_sta_deinit(void)
{
    if (!sta_initialized) return;
    esp_wifi_stop();
    esp_wifi_deinit();
    esp_event_handler_instance_unregister(WIFI_EVENT, ESP_EVENT_ANY_ID, sta_any_id_handle);
    esp_event_handler_instance_unregister(IP_EVENT, IP_EVENT_STA_GOT_IP, sta_got_ip_handle);
    esp_event_loop_delete_default();
    esp_netif_destroy_default_wifi(sta_netif);
    sta_netif = NULL;
    vEventGroupDelete(wifi_event_group);
    wifi_event_group = NULL;
    sta_initialized = false;
}

static bool wifi_try_connect(const char *ssid, const char *pass)
{
    ESP_LOGI(TAG, "Trying WiFi: '%s'", ssid);
    wifi_retry_count = 0;
    xEventGroupClearBits(wifi_event_group, WIFI_CONNECTED_BIT);

    wifi_config_t wifi_config = {0};
    strncpy((char *)wifi_config.sta.ssid, ssid, sizeof(wifi_config.sta.ssid) - 1);
    strncpy((char *)wifi_config.sta.password, pass, sizeof(wifi_config.sta.password) - 1);
    wifi_config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    wifi_config.sta.pmf_cfg.capable = true;
    wifi_config.sta.pmf_cfg.required = false;
    wifi_config.sta.scan_method = WIFI_ALL_CHANNEL_SCAN;
    wifi_config.sta.sort_method = WIFI_CONNECT_AP_BY_SIGNAL;

    esp_wifi_stop();
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    EventBits_t bits = xEventGroupWaitBits(wifi_event_group, WIFI_CONNECTED_BIT,
                                            pdFALSE, pdFALSE, pdMS_TO_TICKS(15000));
    if (bits & WIFI_CONNECTED_BIT) {
        return true;
    }

    ESP_LOGW(TAG, "WiFi '%s' failed", ssid);
    return false;
}

// Scan visible networks, then try saved credentials that match (best signal first)
static bool wifi_try_saved_networks(wifi_cred_t *creds, int cred_count)
{
    if (cred_count == 0) return false;

    // Do a scan to see what's available
    ESP_LOGI(TAG, "Scanning for saved networks...");
    xEventGroupClearBits(wifi_event_group, WIFI_CONNECTED_BIT);

    wifi_config_t empty_config = {0};
    esp_wifi_stop();
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &empty_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    wifi_scan_config_t scan_cfg = {
        .show_hidden = false,
        .scan_type = WIFI_SCAN_TYPE_ACTIVE,
        .scan_time.active.min = 100,
        .scan_time.active.max = 300,
    };
    esp_wifi_scan_start(&scan_cfg, true);  // blocking scan

    uint16_t ap_count = 0;
    esp_wifi_scan_get_ap_num(&ap_count);
    if (ap_count == 0) {
        ESP_LOGW(TAG, "No networks found in scan");
        esp_wifi_scan_get_ap_records(&ap_count, NULL);  // clear scan results
        return false;
    }
    if (ap_count > 20) ap_count = 20;

    wifi_ap_record_t *ap_list = malloc(ap_count * sizeof(wifi_ap_record_t));
    if (!ap_list) return false;
    esp_wifi_scan_get_ap_records(&ap_count, ap_list);

    ESP_LOGI(TAG, "Found %d networks, checking against %d saved", ap_count, cred_count);

    // Build list of matches sorted by signal strength (ap_list is already sorted by RSSI)
    for (int i = 0; i < ap_count; i++) {
        for (int j = 0; j < cred_count; j++) {
            if (strcmp((char *)ap_list[i].ssid, creds[j].ssid) == 0) {
                ESP_LOGI(TAG, "Found saved network '%s' (RSSI %d)", creds[j].ssid, ap_list[i].rssi);
                esp_wifi_stop();
                if (wifi_try_connect(creds[j].ssid, creds[j].pass)) {
                    free(ap_list);
                    return true;
                }
                break;  // Don't try same SSID twice
            }
        }
    }

    free(ap_list);
    return false;
}

// --- URL decode helper ---

static void url_decode(char *dst, const char *src, size_t dst_size)
{
    size_t di = 0;
    for (size_t si = 0; src[si] && di < dst_size - 1; si++) {
        if (src[si] == '%' && src[si+1] && src[si+2]) {
            char hex[3] = { src[si+1], src[si+2], 0 };
            dst[di++] = (char)strtol(hex, NULL, 16);
            si += 2;
        } else if (src[si] == '+') {
            dst[di++] = ' ';
        } else {
            dst[di++] = src[si];
        }
    }
    dst[di] = '\0';
}

// --- Captive portal HTML ---

static bool device_provisioned = false;  // Set before portal starts

static const char CAPTIVE_PORTAL_HTML_WIFI_ONLY[] =
"<!DOCTYPE html><html><head>"
"<meta name='viewport' content='width=device-width,initial-scale=1'>"
"<title>Polly WiFi Setup</title>"
"<style>"
"body{font-family:sans-serif;background:#1a1a2e;color:#e0e0e0;margin:0;padding:20px;}"
"h1{color:#4fc3f7;text-align:center;font-size:24px;}"
"h2{color:#81d4fa;font-size:18px;margin-top:20px;}"
".net{background:#16213e;padding:12px;margin:6px 0;border-radius:8px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;}"
".net:active{background:#0f3460;}"
".bars{color:#4fc3f7;font-size:16px;}"
"input{width:100%;padding:12px;margin:8px 0;border:1px solid #333;border-radius:8px;background:#16213e;color:#e0e0e0;font-size:16px;box-sizing:border-box;}"
"button{width:100%;padding:14px;margin:8px 0;border:none;border-radius:8px;font-size:18px;cursor:pointer;}"
".scan-btn{background:#0f3460;color:#4fc3f7;}"
".connect-btn{background:#4fc3f7;color:#1a1a2e;font-weight:bold;}"
".status{text-align:center;padding:10px;color:#81d4fa;}"
".parrot{text-align:center;font-size:48px;margin:10px 0;}"
"</style></head><body>"
"<div class='parrot'>&#x1F99C;</div>"
"<h1>Polly WiFi Setup</h1>"
"<button class='scan-btn' onclick='scan()'>Scan for Networks</button>"
"<div id='nets'></div>"
"<h2>WiFi Network</h2>"
"<input id='ssid' placeholder='Network name (SSID)'>"
"<input id='pass' type='password' placeholder='Password'>"
"<button class='connect-btn' onclick='save()'>Connect</button>"
"<div id='status' class='status'></div>"
"<script>"
"function scan(){"
"document.getElementById('status').innerText='Scanning...';"
"fetch('/scan').then(r=>r.json()).then(d=>{"
"let h='';"
"d.forEach(n=>{"
"let b=n.rssi>-50?'\\u2589\\u2589\\u2589\\u2589':n.rssi>-65?'\\u2589\\u2589\\u2589':n.rssi>-75?'\\u2589\\u2589':'\\u2589';"
"h+='<div class=\"net\" onclick=\"document.getElementById(\\'ssid\\').value=\\''+n.ssid.replace(/'/g,'\\\\\\'')+'\\'\">';"
"h+='<span>'+n.ssid+'</span><span class=\"bars\">'+b+'</span></div>';"
"});"
"document.getElementById('nets').innerHTML=h;"
"document.getElementById('status').innerText=d.length+' networks found';"
"}).catch(e=>{document.getElementById('status').innerText='Scan failed';});"
"}"
"function save(){"
"let s=document.getElementById('ssid').value,p=document.getElementById('pass').value;"
"if(!s){document.getElementById('status').innerText='Enter a network name';return;}"
"document.getElementById('status').innerText='Saving... Polly will reboot!';"
"fetch('/connect',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},"
"body:'ssid='+encodeURIComponent(s)+'&password='+encodeURIComponent(p)"
"}).then(r=>r.text()).then(t=>{"
"document.getElementById('status').innerText='Saved! Polly is rebooting...';"
"}).catch(e=>{document.getElementById('status').innerText='Error: '+e;});"
"}"
"scan();"
"</script></body></html>";

static const char CAPTIVE_PORTAL_HTML_WITH_CLAIM[] =
"<!DOCTYPE html><html><head>"
"<meta name='viewport' content='width=device-width,initial-scale=1'>"
"<title>Polly WiFi Setup</title>"
"<style>"
"body{font-family:sans-serif;background:#1a1a2e;color:#e0e0e0;margin:0;padding:20px;}"
"h1{color:#4fc3f7;text-align:center;font-size:24px;}"
"h2{color:#81d4fa;font-size:18px;margin-top:20px;}"
".net{background:#16213e;padding:12px;margin:6px 0;border-radius:8px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;}"
".net:active{background:#0f3460;}"
".bars{color:#4fc3f7;font-size:16px;}"
"input{width:100%;padding:12px;margin:8px 0;border:1px solid #333;border-radius:8px;background:#16213e;color:#e0e0e0;font-size:16px;box-sizing:border-box;}"
".claim-input{font-size:24px;text-align:center;letter-spacing:8px;font-weight:bold;}"
"button{width:100%;padding:14px;margin:8px 0;border:none;border-radius:8px;font-size:18px;cursor:pointer;}"
".scan-btn{background:#0f3460;color:#4fc3f7;}"
".connect-btn{background:#4fc3f7;color:#1a1a2e;font-weight:bold;}"
".status{text-align:center;padding:10px;color:#81d4fa;}"
".parrot{text-align:center;font-size:48px;margin:10px 0;}"
".hint{font-size:12px;color:#81d4fa;text-align:center;margin-top:4px;}"
"</style></head><body>"
"<div class='parrot'>&#x1F99C;</div>"
"<h1>Polly WiFi Setup</h1>"
"<h2>Claim Code</h2>"
"<p class='hint'>Enter the 6-digit code from your Polly card</p>"
"<input id='code' class='claim-input' placeholder='000000' maxlength='6' inputmode='numeric' pattern='[0-9]*'>"
"<button class='scan-btn' onclick='scan()'>Scan for Networks</button>"
"<div id='nets'></div>"
"<h2>WiFi Network</h2>"
"<input id='ssid' placeholder='Network name (SSID)'>"
"<input id='pass' type='password' placeholder='Password'>"
"<button class='connect-btn' onclick='save()'>Connect</button>"
"<div id='status' class='status'></div>"
"<script>"
"function scan(){"
"document.getElementById('status').innerText='Scanning...';"
"fetch('/scan').then(r=>r.json()).then(d=>{"
"let h='';"
"d.forEach(n=>{"
"let b=n.rssi>-50?'\\u2589\\u2589\\u2589\\u2589':n.rssi>-65?'\\u2589\\u2589\\u2589':n.rssi>-75?'\\u2589\\u2589':'\\u2589';"
"h+='<div class=\"net\" onclick=\"document.getElementById(\\'ssid\\').value=\\''+n.ssid.replace(/'/g,'\\\\\\'')+'\\'\">';"
"h+='<span>'+n.ssid+'</span><span class=\"bars\">'+b+'</span></div>';"
"});"
"document.getElementById('nets').innerHTML=h;"
"document.getElementById('status').innerText=d.length+' networks found';"
"}).catch(e=>{document.getElementById('status').innerText='Scan failed';});"
"}"
"function save(){"
"let s=document.getElementById('ssid').value,p=document.getElementById('pass').value,c=document.getElementById('code').value;"
"if(!s){document.getElementById('status').innerText='Enter a network name';return;}"
"if(!c||c.length!==6){document.getElementById('status').innerText='Enter your 6-digit claim code';return;}"
"document.getElementById('status').innerText='Saving... Polly will reboot!';"
"fetch('/connect',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},"
"body:'ssid='+encodeURIComponent(s)+'&password='+encodeURIComponent(p)+'&claim_code='+encodeURIComponent(c)"
"}).then(r=>r.text()).then(t=>{"
"document.getElementById('status').innerText='Saved! Polly is rebooting...';"
"}).catch(e=>{document.getElementById('status').innerText='Error: '+e;});"
"}"
"scan();"
"</script></body></html>";

// --- DNS redirect (captive portal trigger) ---

static void dns_redirect_task(void *arg)
{
    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sock < 0) {
        ESP_LOGE(TAG, "DNS socket failed");
        vTaskDelete(NULL);
        return;
    }

    struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_port = htons(53),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    bind(sock, (struct sockaddr *)&addr, sizeof(addr));

    // Set receive timeout so we can check for task deletion
    struct timeval tv = { .tv_sec = 2, .tv_usec = 0 };
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    uint8_t buf[512];
    struct sockaddr_in client;
    socklen_t client_len;

    ESP_LOGI(TAG, "DNS redirect server started on port 53");

    while (1) {
        client_len = sizeof(client);
        int len = recvfrom(sock, buf, sizeof(buf), 0, (struct sockaddr *)&client, &client_len);
        if (len < 12) continue;  // too short or timeout

        // Build DNS response
        uint8_t resp[512];
        memcpy(resp, buf, len);  // copy query

        // Set flags: QR=1, AA=1, no error
        resp[2] = 0x84;
        resp[3] = 0x00;
        // ANCOUNT = 1
        resp[6] = 0x00;
        resp[7] = 0x01;

        // Append answer after the query section
        int pos = len;
        // Name pointer to question
        resp[pos++] = 0xC0;
        resp[pos++] = 0x0C;
        // Type A
        resp[pos++] = 0x00; resp[pos++] = 0x01;
        // Class IN
        resp[pos++] = 0x00; resp[pos++] = 0x01;
        // TTL = 60
        resp[pos++] = 0x00; resp[pos++] = 0x00; resp[pos++] = 0x00; resp[pos++] = 0x3C;
        // RDLENGTH = 4
        resp[pos++] = 0x00; resp[pos++] = 0x04;
        // IP = 192.168.4.1
        resp[pos++] = 192; resp[pos++] = 168; resp[pos++] = 4; resp[pos++] = 1;

        sendto(sock, resp, pos, 0, (struct sockaddr *)&client, client_len);
    }

    close(sock);
    vTaskDelete(NULL);
}

// --- HTTP handlers ---

static esp_err_t portal_get_handler(httpd_req_t *req)
{
    const char *uri = req->uri;

    // /scan endpoint: return JSON list of WiFi networks
    if (strstr(uri, "/scan")) {
        // Need APSTA mode for scanning
        esp_wifi_set_mode(WIFI_MODE_APSTA);
        vTaskDelay(pdMS_TO_TICKS(100));

        wifi_scan_config_t scan_cfg = { .show_hidden = false };
        esp_wifi_scan_start(&scan_cfg, true);

        uint16_t ap_count = 0;
        esp_wifi_scan_get_ap_num(&ap_count);
        if (ap_count > 20) ap_count = 20;

        wifi_ap_record_t *ap_list = malloc(ap_count * sizeof(wifi_ap_record_t));
        esp_wifi_scan_get_ap_records(&ap_count, ap_list);

        // Back to AP only
        esp_wifi_set_mode(WIFI_MODE_AP);

        // Build JSON
        char *json = malloc(2048);
        int offset = 0;
        offset += snprintf(json + offset, 2048 - offset, "[");

        // Deduplicate by SSID
        for (int i = 0; i < ap_count && offset < 1900; i++) {
            if (strlen((char *)ap_list[i].ssid) == 0) continue;

            // Check for duplicate SSID
            bool dup = false;
            for (int j = 0; j < i; j++) {
                if (strcmp((char *)ap_list[i].ssid, (char *)ap_list[j].ssid) == 0) {
                    dup = true;
                    break;
                }
            }
            if (dup) continue;

            if (offset > 1) offset += snprintf(json + offset, 2048 - offset, ",");
            offset += snprintf(json + offset, 2048 - offset,
                "{\"ssid\":\"%s\",\"rssi\":%d,\"auth\":%d}",
                (char *)ap_list[i].ssid, ap_list[i].rssi, ap_list[i].authmode);
        }
        offset += snprintf(json + offset, 2048 - offset, "]");

        httpd_resp_set_type(req, "application/json");
        httpd_resp_send(req, json, offset);

        free(ap_list);
        free(json);
        return ESP_OK;
    }

    // All other GETs: serve captive portal HTML (with or without claim code field)
    httpd_resp_set_type(req, "text/html");
    if (device_provisioned) {
        httpd_resp_send(req, CAPTIVE_PORTAL_HTML_WIFI_ONLY, sizeof(CAPTIVE_PORTAL_HTML_WIFI_ONLY) - 1);
    } else {
        httpd_resp_send(req, CAPTIVE_PORTAL_HTML_WITH_CLAIM, sizeof(CAPTIVE_PORTAL_HTML_WITH_CLAIM) - 1);
    }
    return ESP_OK;
}

static esp_err_t portal_post_handler(httpd_req_t *req)
{
    char body[320] = {0};
    int len = httpd_req_recv(req, body, sizeof(body) - 1);
    if (len <= 0) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "No data");
        return ESP_FAIL;
    }
    body[len] = '\0';

    // Parse ssid=...&password=...&claim_code=...
    char raw_ssid[65] = {0}, raw_pass[65] = {0}, raw_claim[8] = {0};
    char *ssid_start = strstr(body, "ssid=");
    char *pass_start = strstr(body, "password=");
    char *claim_start = strstr(body, "claim_code=");

    if (ssid_start) {
        ssid_start += 5;
        char *end = strchr(ssid_start, '&');
        if (end) *end = '\0';
        url_decode(raw_ssid, ssid_start, sizeof(raw_ssid));
        if (end) *end = '&';
    }
    if (pass_start) {
        pass_start += 9;
        char *end = strchr(pass_start, '&');
        if (end) *end = '\0';
        url_decode(raw_pass, pass_start, sizeof(raw_pass));
        if (end) *end = '&';
    }
    if (claim_start) {
        claim_start += 11;
        char *end = strchr(claim_start, '&');
        if (end) *end = '\0';
        url_decode(raw_claim, claim_start, sizeof(raw_claim));
    }

    if (strlen(raw_ssid) == 0) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "SSID required");
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "Portal: saving WiFi '%s'", raw_ssid);
    wifi_nvs_save(raw_ssid, raw_pass);

    // Save claim code to NVS if provided (will be used after WiFi connects)
    if (strlen(raw_claim) > 0) {
        ESP_LOGI(TAG, "Portal: saving claim code to NVS");
        device_nvs_save_claim_code(raw_claim);
    }

    const char *resp = "<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<style>body{font-family:sans-serif;background:#1a1a2e;color:#e0e0e0;text-align:center;padding:40px;}"
        "h1{color:#4fc3f7;}</style></head><body>"
        "<h1>&#x1F99C; Saved!</h1><p>Polly is rebooting and will connect to your WiFi.</p>"
        "<p>You can close this page.</p></body></html>";
    httpd_resp_set_type(req, "text/html");
    httpd_resp_send(req, resp, strlen(resp));

    // Give the response time to send, then reboot
    xSemaphoreGive(provision_done_sem);

    return ESP_OK;
}

// --- Captive portal start ---

static void captive_portal_start(void)
{
    ESP_LOGI(TAG, "Starting WiFi provisioning (AP mode)...");

    provision_done_sem = xSemaphoreCreateBinary();

    // Init WiFi in AP mode
    wifi_event_group = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    ap_netif = esp_netif_create_default_wifi_ap();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    wifi_config_t ap_config = {
        .ap = {
            .ssid = "Polly-Setup",
            .ssid_len = 11,
            .password = "",
            .max_connection = 2,
            .authmode = WIFI_AUTH_OPEN,
            .channel = 1,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &ap_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "AP 'Polly-Setup' started. Connect and go to 192.168.4.1");

    // Start DNS redirect for captive portal auto-open
    xTaskCreate(dns_redirect_task, "dns_redirect", 4096, NULL, 5, &dns_task_handle);

    // Start HTTP server
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.max_uri_handlers = 8;
    config.uri_match_fn = httpd_uri_match_wildcard;
    config.lru_purge_enable = true;

    ESP_ERROR_CHECK(httpd_start(&portal_server, &config));

    httpd_uri_t post_uri = {
        .uri = "/connect",
        .method = HTTP_POST,
        .handler = portal_post_handler,
    };
    httpd_register_uri_handler(portal_server, &post_uri);

    // Wildcard GET must be registered AFTER specific routes
    httpd_uri_t get_uri = {
        .uri = "/*",
        .method = HTTP_GET,
        .handler = portal_get_handler,
    };
    httpd_register_uri_handler(portal_server, &get_uri);

    // Blink LED: slow blink = provisioning mode
    ESP_LOGI(TAG, "Waiting for WiFi credentials via captive portal...");

    // Block until credentials submitted (blink LED while waiting)
    while (xSemaphoreTake(provision_done_sem, pdMS_TO_TICKS(500)) != pdTRUE) {
        static bool led_on = false;
        led_on = !led_on;
        led_set(led_on ? 1 : 0);
    }

    led_set(1);
    ESP_LOGI(TAG, "Credentials received! Rebooting in 2 seconds...");
    vTaskDelay(pdMS_TO_TICKS(2000));
    esp_restart();
}

// --- Device provisioning via server (claim code → credentials) ---

static bool device_provision_from_server(void)
{
    char claim_code[8] = {0};
    if (!device_nvs_load_claim_code(claim_code, sizeof(claim_code))) {
        ESP_LOGI(TAG, "No claim code in NVS — skipping server provisioning");
        return false;
    }

    ESP_LOGI(TAG, "Provisioning device with claim code: %s", claim_code);

    // Build JSON body
    char post_body[64];
    snprintf(post_body, sizeof(post_body), "{\"claim_code\":\"%s\"}", claim_code);

    // Build URL
    char url[128];
    snprintf(url, sizeof(url), "http://%s:%d/api/devices/provision", SERVER_HOST, SERVER_PORT);

    esp_http_client_config_t cfg = {
        .url = url,
        .timeout_ms = 10000,
    };
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    esp_http_client_set_method(client, HTTP_METHOD_POST);
    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_post_field(client, post_body, strlen(post_body));

    esp_err_t err = esp_http_client_perform(client);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Provisioning HTTP request failed: %s", esp_err_to_name(err));
        esp_http_client_cleanup(client);
        return false;
    }

    int status = esp_http_client_get_status_code(client);
    int content_len = esp_http_client_get_content_length(client);
    ESP_LOGI(TAG, "Provisioning response: status=%d, len=%d", status, content_len);

    if (status != 200 || content_len <= 0 || content_len > 512) {
        ESP_LOGE(TAG, "Provisioning failed — invalid claim code or server error");
        esp_http_client_cleanup(client);
        return false;
    }

    // Read response body — need to re-request with open/read pattern
    esp_http_client_cleanup(client);

    // Re-do with open/read to get body
    client = esp_http_client_init(&cfg);
    esp_http_client_set_method(client, HTTP_METHOD_POST);
    esp_http_client_set_header(client, "Content-Type", "application/json");

    err = esp_http_client_open(client, strlen(post_body));
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Provisioning open failed");
        esp_http_client_cleanup(client);
        return false;
    }
    esp_http_client_write(client, post_body, strlen(post_body));
    content_len = esp_http_client_fetch_headers(client);
    status = esp_http_client_get_status_code(client);

    if (status != 200 || content_len <= 0) {
        ESP_LOGE(TAG, "Provisioning failed: status=%d", status);
        esp_http_client_cleanup(client);
        return false;
    }

    char *resp = calloc(1, content_len + 1);
    if (!resp) {
        esp_http_client_cleanup(client);
        return false;
    }
    esp_http_client_read(client, resp, content_len);
    esp_http_client_cleanup(client);

    // Simple JSON parse for device_id and api_key
    char new_device_id[64] = {0}, new_api_key[64] = {0};
    char *did_start = strstr(resp, "\"device_id\"");
    char *key_start = strstr(resp, "\"api_key\"");

    if (did_start) {
        did_start = strchr(did_start + 11, '"');
        if (did_start) {
            did_start++;
            char *end = strchr(did_start, '"');
            if (end && (end - did_start) < (int)sizeof(new_device_id)) {
                memcpy(new_device_id, did_start, end - did_start);
            }
        }
    }
    if (key_start) {
        key_start = strchr(key_start + 9, '"');
        if (key_start) {
            key_start++;
            char *end = strchr(key_start, '"');
            if (end && (end - key_start) < (int)sizeof(new_api_key)) {
                memcpy(new_api_key, key_start, end - key_start);
            }
        }
    }
    free(resp);

    if (strlen(new_device_id) == 0 || strlen(new_api_key) == 0) {
        ESP_LOGE(TAG, "Provisioning: failed to parse device_id/api_key from response");
        return false;
    }

    ESP_LOGI(TAG, "Provisioning success! device_id=%s", new_device_id);
    device_nvs_save(new_device_id, new_api_key);
    device_nvs_clear_claim_code();

    // Load into globals
    strncpy(g_device_id, new_device_id, sizeof(g_device_id) - 1);
    strncpy(g_api_key, new_api_key, sizeof(g_api_key) - 1);

    return true;
}

// --- Main provisioning init (replaces wifi_init) ---

static void wifi_provision_init(void)
{
    // Load device credentials from NVS (or use fallback defines)
    device_provisioned = device_nvs_load(g_device_id, sizeof(g_device_id),
                                          g_api_key, sizeof(g_api_key));
    if (!device_provisioned) {
        // Use compiled-in fallback for legacy/dev devices
        strncpy(g_device_id, DEVICE_ID_FALLBACK, sizeof(g_device_id) - 1);
        strncpy(g_api_key, DEVICE_API_KEY_FALLBACK, sizeof(g_api_key) - 1);
        ESP_LOGI(TAG, "No device credentials in NVS — using fallback: %s", g_device_id);
    }

    // Check if GPIO0 (BOOT button) is held at startup = force provisioning
    gpio_config_t btn_check = {
        .pin_bit_mask = (1ULL << GPIO_NUM_0),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    gpio_config(&btn_check);

    bool force_provision = false;
    if (gpio_get_level(GPIO_NUM_0) == 0) {
        ESP_LOGW(TAG, "BOOT button held — hold for 3 seconds to enter WiFi setup...");
        vTaskDelay(pdMS_TO_TICKS(3000));
        if (gpio_get_level(GPIO_NUM_0) == 0) {
            ESP_LOGW(TAG, "Entering WiFi provisioning mode!");
            wifi_nvs_clear();
            force_provision = true;
        }
    }

    if (!force_provision) {
        wifi_sta_init();

        // Load all saved networks and try matching ones (best signal first)
        wifi_cred_t creds[WIFI_MAX_SAVED] = {0};
        int count = wifi_nvs_load_all(creds, WIFI_MAX_SAVED);

        // Always include hardcoded home network as fallback
        bool have_hardcoded = false;
        for (int i = 0; i < count; i++) {
            if (strcmp(creds[i].ssid, WIFI_SSID) == 0) { have_hardcoded = true; break; }
        }
        if (!have_hardcoded && count < WIFI_MAX_SAVED) {
            strncpy(creds[count].ssid, WIFI_SSID, sizeof(creds[count].ssid) - 1);
            strncpy(creds[count].pass, WIFI_PASSWORD, sizeof(creds[count].pass) - 1);
            count++;
        }

        if (wifi_try_saved_networks(creds, count)) {
            // Save hardcoded if it was the one that connected (ensures it's in NVS)
            wifi_config_t current = {0};
            esp_wifi_get_config(WIFI_IF_STA, &current);
            if (strcmp((char *)current.sta.ssid, WIFI_SSID) == 0) {
                wifi_nvs_save(WIFI_SSID, WIFI_PASSWORD);
            }

            // WiFi connected — provision device if needed
            if (!device_provisioned) {
                if (device_provision_from_server()) {
                    device_provisioned = true;
                    ESP_LOGI(TAG, "Device provisioned via server: %s", g_device_id);
                } else {
                    ESP_LOGW(TAG, "Device provisioning failed — using fallback credentials");
                }
            }
            return;  // Connected!
        }

        // Scan found nothing — try each saved network directly as fallback
        ESP_LOGI(TAG, "Scan didn't match, trying saved networks directly...");
        for (int i = 0; i < count; i++) {
            if (wifi_try_connect(creds[i].ssid, creds[i].pass)) {
                // WiFi connected — provision device if needed
                if (!device_provisioned) {
                    if (device_provision_from_server()) {
                        device_provisioned = true;
                        ESP_LOGI(TAG, "Device provisioned via server: %s", g_device_id);
                    } else {
                        ESP_LOGW(TAG, "Device provisioning failed — using fallback credentials");
                    }
                }
                return;  // Connected!
            }
        }

        wifi_sta_deinit();
    }

    // All failed or force provision — start captive portal
    captive_portal_start();
    // captive_portal_start blocks until creds saved, then reboots
    // We should never reach here
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

            size_t decoded_len = 0;
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

    } else if (strcmp(evt, "story_record_started") == 0) {
        ESP_LOGI(TAG, "*** STORY RECORDING STARTED ***");
        story_recording = true;
        led_set(1);

    } else if (strcmp(evt, "story_record_stopped") == 0) {
        ESP_LOGI(TAG, "*** STORY RECORDING STOPPED ***");
        story_recording = false;
        led_set(0);

    } else if (strcmp(evt, "no_wake_word") == 0) {
        ESP_LOGI(TAG, "No wake phrase detected, resuming...");
        streaming_paused = false;
        wake_detected = false;
        led_set(0);

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
            streaming_paused = false;       // Reset in case disconnect happened mid-response
            response_complete = false;
            response_audio_len = 0;
            story_recording = false;

            // Send connect event with device identity, API key, and firmware version
            {
                char connect_msg[384];
                snprintf(connect_msg, sizeof(connect_msg),
                    "{\"event\":\"connect\",\"device_id\":\"%s\",\"api_key\":\"%s\","
                    "\"fw_version\":\"%s\",\"fw_variant\":\"%s\"}",
                    g_device_id, g_api_key, FW_VERSION, FW_VARIANT);
                esp_websocket_client_send_text(ws_client, connect_msg,
                                                strlen(connect_msg), pdMS_TO_TICKS(1000));
            }
            break;

        case WEBSOCKET_EVENT_DATA:
            if (data->op_code == 0x01 || data->op_code == 0x00) {
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

                if (data->payload_offset + data->data_len >= data->payload_len) {
                    ws_handle_message(msg_accum, msg_accum_len);
                    msg_accum_len = 0;
                }
            }
            break;

        case WEBSOCKET_EVENT_DISCONNECTED:
            ESP_LOGW(TAG, "WebSocket disconnected");
            ws_connected = false;
            streaming_paused = false;  // Unstick mic loop
            led_set(0);               // LED off to indicate disconnected
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
        .network_timeout_ms = 30000,        // 30s TCP timeout (was 10s — caused idle disconnects)
        .ping_interval_sec = 20,            // RFC 6455 WebSocket ping every 20s (keeps connection alive)
        .pingpong_timeout_sec = 60,         // Allow up to 60s for pong (long recordings block sends)
        .task_stack = 12288,                // 12KB stack for WS task (was 8K — stack overflow on long sessions)
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

    // Enable speaker amplifier
    tca9555_amp_enable(true);

    // Skip WAV header if present
    size_t offset = 0;
    if (response_audio_len > 44 && memcmp(response_audio, "RIFF", 4) == 0) {
        offset = 44;
        ESP_LOGI(TAG, "Skipping WAV header");
    }

    size_t play_len = response_audio_len - offset;
    size_t total_written = 0;
    // Write in chunks to avoid blocking on long audio (prayers, narratives)
    size_t chunk = 16000;  // ~0.5s per chunk at 16kHz 16-bit
    while (total_written < play_len) {
        size_t remaining = play_len - total_written;
        size_t to_write = remaining < chunk ? remaining : chunk;
        size_t written = 0;
        i2s_channel_write(spk_handle, response_audio + offset + total_written,
                          to_write, &written, pdMS_TO_TICKS(5000));
        total_written += written;
        if (written == 0) {
            ESP_LOGW(TAG, "I2S write stalled at %d/%d bytes", (int)total_written, (int)play_len);
            break;
        }
    }

    // Flush DMA with silence
    size_t silence_len = SAMPLE_RATE * sizeof(int16_t) / 4;  // 0.25s
    uint8_t *silence = heap_caps_calloc(1, silence_len, MALLOC_CAP_SPIRAM);
    if (silence) {
        size_t sil_written = 0;
        i2s_channel_write(spk_handle, silence, silence_len, &sil_written, pdMS_TO_TICKS(1000));
        heap_caps_free(silence);
    }

    // Disable speaker amplifier (saves power, reduces noise)
    tca9555_amp_enable(false);

    ESP_LOGI(TAG, "Playback complete (%d/%d bytes written)", (int)total_written, (int)play_len);

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
    uint32_t rms_debug_counter = 0;
    uint32_t disconnect_counter = 0;       // Watchdog: counts ticks while disconnected
    const uint32_t WATCHDOG_REBOOT_MS = 60000;  // Reboot after 60s disconnected
    uint32_t paused_counter = 0;           // Watchdog: counts ticks while stuck in paused state
    const uint32_t PAUSED_REBOOT_MS = 45000;  // Reboot after 45s stuck paused (no response_complete)

    while (1) {
        // Handle wake word detection — just LED, keep streaming
        if (wake_detected) {
            wake_detected = false;
            led_set(1);
        }

        // Handle response playback
        if (response_complete) {
            play_response_audio();
            led_set(0);
            // Cooldown: drain mic buffer so residual speaker audio doesn't trigger wake word
            for (int i = 0; i < 30; i++) {  // ~2 seconds of draining
                mic_read(audio_chunk, CHUNK_SAMPLES);
                vTaskDelay(pdMS_TO_TICKS(50));
            }

            streaming_paused = false;

            // If WebSocket died during playback, force immediate reboot to reconnect
            if (!ws_connected) {
                ESP_LOGW(TAG, "WebSocket lost during playback — rebooting to reconnect");
                vTaskDelay(pdMS_TO_TICKS(500));
                esp_restart();
            }

            ESP_LOGI(TAG, "Back to streaming (heap: %u, PSRAM: %u)",
                     (unsigned)esp_get_free_heap_size(),
                     (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
        }

        // Stream mic audio to server (unless paused for playback)
        if (ws_connected && !streaming_paused) {
            size_t samples = mic_read(audio_chunk, CHUNK_SAMPLES);
            if (samples > 0) {
                // Debug: log RMS every ~3 seconds
                rms_debug_counter++;
                if (rms_debug_counter >= 100) {
                    rms_debug_counter = 0;
                    int64_t sum = 0;
                    for (size_t i = 0; i < samples; i++) {
                        sum += (int64_t)audio_chunk[i] * audio_chunk[i];
                    }
                    uint32_t rms = (uint32_t)sqrt((double)sum / samples);
                    ESP_LOGI(TAG, "Mic RMS: %lu (samples=%d)", rms, (int)samples);
                }

                if (!esp_websocket_client_is_connected(ws_client)) {
                    ws_connected = false;
                    continue;
                }
                int ret = esp_websocket_client_send_bin(
                    ws_client,
                    (const char *)audio_chunk,
                    samples * sizeof(int16_t),
                    pdMS_TO_TICKS(500)  // 500ms timeout (was 2s — long blocks starve ping/pong)
                );
                if (ret < 0) {
                    ESP_LOGW(TAG, "WebSocket send failed (ret=%d), free heap=%u",
                             ret, (unsigned)esp_get_free_heap_size());
                    // Don't immediately disconnect on single failure — retry next loop
                    // Only disconnect on consecutive failures
                    static int send_fail_count = 0;
                    send_fail_count++;
                    if (send_fail_count >= 5) {
                        ws_connected = false;
                        streaming_paused = false;
                        led_set(0);
                        send_fail_count = 0;
                    }
                    vTaskDelay(pdMS_TO_TICKS(100));
                } else {
                    send_fail_count = 0;  // Reset on success
                }
            }
        } else {
            // While paused or disconnected, still read mic to keep I2S flowing
            mic_read(audio_chunk, CHUNK_SAMPLES);
            vTaskDelay(pdMS_TO_TICKS(10));

            // Watchdog: if disconnected too long, reboot (suppress during OTA)
            if (!ws_connected && !ota_in_progress) {
                disconnect_counter += 10;
                if (disconnect_counter >= WATCHDOG_REBOOT_MS) {
                    ESP_LOGE(TAG, "WebSocket disconnected for %lus — rebooting!", WATCHDOG_REBOOT_MS / 1000);
                    vTaskDelay(pdMS_TO_TICKS(500));
                    esp_restart();
                }
            }

            // Watchdog: if stuck in paused state too long (waiting for response_complete
            // that never arrives), force reboot. This catches the case where ws_connected
            // is true but the device is frozen mid-response.
            if (ws_connected && streaming_paused && !ota_in_progress && !story_recording) {
                paused_counter += 10;
                if (paused_counter >= PAUSED_REBOOT_MS) {
                    ESP_LOGE(TAG, "Stuck in paused state for %lus — rebooting!", PAUSED_REBOOT_MS / 1000);
                    vTaskDelay(pdMS_TO_TICKS(500));
                    esp_restart();
                }
            }
        }

        // Reset watchdogs when connected and streaming normally
        if (ws_connected) {
            disconnect_counter = 0;
        }
        if (!streaming_paused) {
            paused_counter = 0;
        }

        // Story button (K1/+) toggle — send start/stop to server
        if (story_button_pressed) {
            story_button_pressed = false;
            if (ws_connected) {
                const char *msg = story_recording
                    ? "{\"event\":\"story_button\",\"action\":\"stop\"}"
                    : "{\"event\":\"story_button\",\"action\":\"start\"}";
                esp_websocket_client_send_text(ws_client, msg, strlen(msg), pdMS_TO_TICKS(1000));
                ESP_LOGI(TAG, "Story button → %s", story_recording ? "stop" : "start");
            }
        }

        // Periodic ping (every ~30 seconds)
        ping_timer++;
        if (ping_timer >= 1000) {
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


/* --- OTA Firmware Update --- */

static void ota_check_task(void *arg)
{
    // Wait for system to stabilize
    vTaskDelay(pdMS_TO_TICKS(30000));

    while (1) {
        if (!ws_connected) {
            vTaskDelay(pdMS_TO_TICKS(60000));
            continue;
        }

        ESP_LOGI(TAG, "OTA: Checking for firmware updates (current: %s)", FW_VERSION);

        // Build check URL
        char url[256];
        snprintf(url, sizeof(url),
            "http://%s:%d/api/firmware/check?device_id=%s&variant=%s&current_version=%s",
            SERVER_HOST, SERVER_PORT, g_device_id, FW_VARIANT, FW_VERSION);

        esp_http_client_config_t check_cfg = {
            .url = url,
            .timeout_ms = 10000,
        };
        esp_http_client_handle_t client = esp_http_client_init(&check_cfg);

        esp_err_t err = esp_http_client_open(client, 0);
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "OTA: Check connection failed: %s", esp_err_to_name(err));
            esp_http_client_cleanup(client);
            vTaskDelay(pdMS_TO_TICKS(3600000));
            continue;
        }

        int content_len = esp_http_client_fetch_headers(client);
        int status = esp_http_client_get_status_code(client);
        if (status != 200 || content_len <= 0 || content_len > 1024) {
            ESP_LOGW(TAG, "OTA: Check failed (status=%d, len=%d)", status, content_len);
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            vTaskDelay(pdMS_TO_TICKS(3600000));
            continue;
        }

        char *resp = malloc(content_len + 1);
        if (!resp) {
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            vTaskDelay(pdMS_TO_TICKS(3600000));
            continue;
        }
        int read_len = esp_http_client_read(client, resp, content_len);
        resp[read_len > 0 ? read_len : 0] = '\0';
        esp_http_client_close(client);
        esp_http_client_cleanup(client);

        // Parse JSON response
        cJSON *root = cJSON_Parse(resp);
        free(resp);
        if (!root) {
            vTaskDelay(pdMS_TO_TICKS(3600000));
            continue;
        }

        cJSON *update = cJSON_GetObjectItem(root, "update_available");
        if (!update || !cJSON_IsTrue(update)) {
            ESP_LOGI(TAG, "OTA: Firmware is up to date");
            cJSON_Delete(root);
            vTaskDelay(pdMS_TO_TICKS(3600000));  // Check again in 1 hour
            continue;
        }

        cJSON *ver = cJSON_GetObjectItem(root, "version");
        cJSON *dl_url = cJSON_GetObjectItem(root, "download_url");
        if (!ver || !dl_url) {
            cJSON_Delete(root);
            vTaskDelay(pdMS_TO_TICKS(3600000));
            continue;
        }

        ESP_LOGI(TAG, "OTA: Update available! %s -> %s", FW_VERSION, ver->valuestring);

        // Build full download URL
        char full_url[256];
        snprintf(full_url, sizeof(full_url), "http://%s:%d%s",
                 SERVER_HOST, SERVER_PORT, dl_url->valuestring);
        cJSON_Delete(root);

        // Wait for audio to finish
        ESP_LOGI(TAG, "OTA: Waiting for audio idle...");
        int wait_count = 0;
        while ((streaming_paused || story_recording) && wait_count < 60) {
            vTaskDelay(pdMS_TO_TICKS(1000));
            wait_count++;
        }

        ota_in_progress = true;
        ESP_LOGI(TAG, "OTA: Starting download from %s", full_url);

        // Perform OTA
        const esp_partition_t *update_partition = esp_ota_get_next_update_partition(NULL);
        if (!update_partition) {
            ESP_LOGE(TAG, "OTA: No update partition found!");
            ota_in_progress = false;
            vTaskDelay(pdMS_TO_TICKS(3600000));
            continue;
        }

        ESP_LOGI(TAG, "OTA: Writing to partition '%s' at 0x%"PRIx32,
                 update_partition->label, update_partition->address);

        esp_http_client_config_t dl_cfg = {
            .url = full_url,
            .timeout_ms = 30000,
        };
        esp_http_client_handle_t dl_client = esp_http_client_init(&dl_cfg);
        esp_http_client_set_header(dl_client, "X-API-Key", g_api_key);
        esp_http_client_open(dl_client, 0);
        int total_len = esp_http_client_fetch_headers(dl_client);
        if (total_len <= 0) {
            ESP_LOGE(TAG, "OTA: Download failed — no content");
            esp_http_client_cleanup(dl_client);
            ota_in_progress = false;
            vTaskDelay(pdMS_TO_TICKS(3600000));
            continue;
        }

        esp_ota_handle_t ota_handle;
        err = esp_ota_begin(update_partition, total_len, &ota_handle);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "OTA: esp_ota_begin failed: %s", esp_err_to_name(err));
            esp_http_client_cleanup(dl_client);
            ota_in_progress = false;
            vTaskDelay(pdMS_TO_TICKS(3600000));
            continue;
        }

        char *buf = malloc(4096);
        int received = 0;
        bool ota_ok = true;
        while (received < total_len) {
            int read_len = esp_http_client_read(dl_client, buf, 4096);
            if (read_len <= 0) {
                ESP_LOGE(TAG, "OTA: Read error at %d/%d bytes", received, total_len);
                ota_ok = false;
                break;
            }
            err = esp_ota_write(ota_handle, buf, read_len);
            if (err != ESP_OK) {
                ESP_LOGE(TAG, "OTA: Write error: %s", esp_err_to_name(err));
                ota_ok = false;
                break;
            }
            received += read_len;
            if (received % (100 * 1024) == 0 || received == total_len) {
                ESP_LOGI(TAG, "OTA: %d/%d bytes (%d%%)", received, total_len, received * 100 / total_len);
            }
        }
        free(buf);
        esp_http_client_cleanup(dl_client);

        if (!ota_ok) {
            esp_ota_abort(ota_handle);
            ota_in_progress = false;
            vTaskDelay(pdMS_TO_TICKS(3600000));
            continue;
        }

        err = esp_ota_end(ota_handle);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "OTA: Validation failed: %s", esp_err_to_name(err));
            ota_in_progress = false;
            vTaskDelay(pdMS_TO_TICKS(3600000));
            continue;
        }

        err = esp_ota_set_boot_partition(update_partition);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "OTA: Set boot partition failed: %s", esp_err_to_name(err));
            ota_in_progress = false;
            vTaskDelay(pdMS_TO_TICKS(3600000));
            continue;
        }

        ESP_LOGI(TAG, "OTA: Update successful! Rebooting...");
        vTaskDelay(pdMS_TO_TICKS(1000));
        esp_restart();
    }
}


/* --- App Main --- */

void app_main(void)
{
    ESP_LOGI(TAG, "=== Polly Connect - Waveshare ESP32-S3-AUDIO-Board ===");
    ESP_LOGI(TAG, "Firmware: v%s (%s)", FW_VERSION, FW_VARIANT);
    ESP_LOGI(TAG, "Free heap: %u bytes", (unsigned)esp_get_free_heap_size());
    ESP_LOGI(TAG, "Free PSRAM: %u bytes", (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));

    // Init NVS (needed for WiFi)
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    // OTA rollback validation — mark this firmware as good if we just updated
    const esp_partition_t *running = esp_ota_get_running_partition();
    esp_ota_img_states_t ota_state;
    if (esp_ota_get_state_partition(running, &ota_state) == ESP_OK) {
        if (ota_state == ESP_OTA_IMG_PENDING_VERIFY) {
            ESP_LOGI(TAG, "OTA: First boot after update — marking firmware valid");
            esp_ota_mark_app_valid_cancel_rollback();
        }
    }
    ESP_LOGI(TAG, "Running from partition: %s", running->label);

    // Init LED
    led_init();
    led_set(1);

    // Init I2C bus (must come before codec init)
    ESP_ERROR_CHECK(i2c_init());

    // Scan I2C bus to verify devices are present
    i2c_scan();

    // Init TCA9555 port expander (must come before codecs — controls amp power)
    tca9555_init();

    // Init I2S FIRST — codecs need MCLK running before register writes take effect
    ESP_ERROR_CHECK(audio_i2s_init());

    // Small delay to let MCLK stabilize
    vTaskDelay(pdMS_TO_TICKS(50));

    // NOW init audio codecs via I2C (MCLK is running)
    es8311_init();
    es7210_init();

    // Small settle time after codec init
    vTaskDelay(pdMS_TO_TICKS(50));

    // Init WiFi (with provisioning — checks NVS, fallback to AP captive portal)
    wifi_provision_init();

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

    // Amp off until we need to play audio
    tca9555_amp_enable(false);

    led_set(0);
    ESP_LOGI(TAG, "Setup complete. Streaming audio to server...");

    // Start story button polling task (K1/+ via TCA9555 I/O expander)
    xTaskCreate(story_button_task, "story_btn", 2048, NULL, 3, NULL);

    // Start mic streaming task on core 1 (core 0 handles WiFi/WebSocket)
    xTaskCreatePinnedToCore(mic_stream_task, "mic_stream", 8192, NULL, 5, NULL, 1);

    // Start OTA update checker (low priority, checks every hour)
    xTaskCreate(ota_check_task, "ota_check", 8192, NULL, 2, NULL);
}
