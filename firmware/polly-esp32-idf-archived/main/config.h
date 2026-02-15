#ifndef CONFIG_H
#define CONFIG_H

#include "driver/gpio.h"

// WiFi Configuration
#define WIFI_SSID           CONFIG_WIFI_SSID
#define WIFI_PASSWORD       CONFIG_WIFI_PASSWORD
#define MAX_RETRY           CONFIG_WIFI_MAXIMUM_RETRY

// Server Configuration
#define SERVER_URI          CONFIG_SERVER_URI

// Audio Configuration
#define SAMPLE_RATE         16000
#define BITS_PER_SAMPLE     16
#define CHANNELS            1
#define FRAME_SIZE          512        // Porcupine frame size
#define FRAME_SIZE_BYTES    (FRAME_SIZE * 2)

// Buffer Configuration
#define AUDIO_BUFFER_SECS   CONFIG_AUDIO_BUFFER_SECONDS
#define AUDIO_BUFFER_SIZE   (SAMPLE_RATE * AUDIO_BUFFER_SECS * 2)

// GPIO Configuration (INMP441)
#define I2S_WS              GPIO_NUM_42
#define I2S_SD              GPIO_NUM_41
#define I2S_SCK             GPIO_NUM_40

// Porcupine Configuration
#define PORCUPINE_ACCESS_KEY    CONFIG_PORCUPINE_ACCESS_KEY
#define PORCUPINE_SENSITIVITY   0.5f

// Task Configuration
#define TASK_STACK_AUDIO        (8 * 1024)
#define TASK_STACK_WAKE         (16 * 1024)
#define TASK_STACK_STREAM       (8 * 1024)
#define TASK_STACK_WEBSOCKET    (8 * 1024)

// Task Priorities
#define TASK_PRIORITY_AUDIO     5
#define TASK_PRIORITY_WAKE      6
#define TASK_PRIORITY_STREAM    5
#define TASK_PRIORITY_WEBSOCKET 4

// Audio streaming configuration
#define STREAMING_DURATION_SEC  5      // Maximum command duration in seconds
#define STREAMING_MAX_FRAMES    ((STREAMING_DURATION_SEC * SAMPLE_RATE) / FRAME_SIZE)

#endif // CONFIG_H
