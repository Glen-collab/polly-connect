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

static const char *TAG = "POLLY-WS";

/* --- Configuration --- */

// WiFi
#define WIFI_SSID       "SpectrumSetup-73"
#define WIFI_PASSWORD   "orangegate448"
#define WIFI_MAX_RETRY  10

// Server
#define SERVER_HOST     "3.14.130.158"
#define SERVER_PORT     8000
#define WS_URI          "ws://" SERVER_HOST ":8000/api/audio/continuous"

// Device identity & API key (change per-device)
#define DEVICE_ID       "polly-waveshare"
#define DEVICE_API_KEY  "qtde_XgbmZ2jExSBRH0jtsKIgjMkcEwl-BoabvVj7GE"

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
#define TCA_PA_PIN      0x01    // Port 1 bit 0: speaker amplifier enable

// Status LED (WS2812 RGB on GPIO48, driven as simple GPIO)
#define LED_PIN         GPIO_NUM_48

// Audio
#define SAMPLE_RATE     16000
#define CHUNK_SAMPLES   480         // 30ms chunks for streaming
#define CHUNK_BYTES     (CHUNK_SAMPLES * sizeof(int16_t))  // 960 bytes

// WebSocket
#define WS_BUFFER_SIZE  4096
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

// Flags set by WebSocket event handler, consumed by streaming task
static volatile bool wake_detected = false;
static volatile bool streaming_paused = false;

// Story recording state
static volatile bool story_recording = false;

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
    i2c_write_reg(TCA9555_ADDR, 0x03, on ? TCA_PA_PIN : 0x00);
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

            // Send connect event with device identity and API key
            {
                char connect_msg[256];
                snprintf(connect_msg, sizeof(connect_msg),
                    "{\"event\":\"connect\",\"device_id\":\"%s\",\"api_key\":\"%s\"}",
                    DEVICE_ID, DEVICE_API_KEY);
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
        .network_timeout_ms = 10000,
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

    // Enable speaker amplifier
    tca9555_amp_enable(true);

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
    uint32_t rms_debug_counter = 0;

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
            ESP_LOGI(TAG, "Back to streaming...");
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
                    pdMS_TO_TICKS(2000)
                );
                if (ret < 0) {
                    ESP_LOGW(TAG, "WebSocket send failed (ret=%d), free heap=%u",
                             ret, (unsigned)esp_get_free_heap_size());
                    vTaskDelay(pdMS_TO_TICKS(100));
                }
            }
        } else {
            // While paused or disconnected, still read mic to keep I2S flowing
            mic_read(audio_chunk, CHUNK_SAMPLES);
            vTaskDelay(pdMS_TO_TICKS(10));
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


/* --- App Main --- */

void app_main(void)
{
    ESP_LOGI(TAG, "=== Polly Connect - Waveshare ESP32-S3-AUDIO-Board ===");
    ESP_LOGI(TAG, "Free heap: %u bytes", (unsigned)esp_get_free_heap_size());
    ESP_LOGI(TAG, "Free PSRAM: %u bytes", (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));

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

    // Amp off until we need to play audio
    tca9555_amp_enable(false);

    led_set(0);
    ESP_LOGI(TAG, "Setup complete. Streaming audio to server...");

    // Start mic streaming task on core 1 (core 0 handles WiFi/WebSocket)
    xTaskCreatePinnedToCore(mic_stream_task, "mic_stream", 8192, NULL, 5, NULL, 1);
}
