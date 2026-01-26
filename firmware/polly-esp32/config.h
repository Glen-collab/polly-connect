/**
 * Polly Connect - ESP32 Configuration
 * 
 * Edit these values for your setup!
 */

#ifndef CONFIG_H
#define CONFIG_H

// === WiFi Settings ===
#define WIFI_SSID     "YOUR_WIFI_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"

// === Server Settings ===
// During development, use your Pi's IP address
// For production, use your cloud server URL
#define SERVER_HOST   "192.168.1.100"  // Your Pi or server IP
#define SERVER_PORT   8000
#define SERVER_PATH   "/api/audio/stream"

// === Device Identity ===
#define DEVICE_ID     "polly001"

// === Audio Settings ===
#define SAMPLE_RATE   16000
#define BITS_PER_SAMPLE 16
#define CHUNK_SIZE    4096  // Bytes per WebSocket message

// === I2S Microphone Pins (INMP441) ===
#define I2S_MIC_SERIAL_CLOCK   33  // SCK
#define I2S_MIC_WORD_SELECT    25  // WS
#define I2S_MIC_SERIAL_DATA    32  // SD

// === I2S Speaker Pins (MAX98357A) ===
#define I2S_SPK_SERIAL_CLOCK   26  // BCLK
#define I2S_SPK_WORD_SELECT    21  // LRC
#define I2S_SPK_SERIAL_DATA    22  // DIN

// === Silence Detection ===
#define SILENCE_THRESHOLD  500   // Adjust based on your mic sensitivity
#define SILENCE_TIMEOUT_MS 1500  // Stop recording after 1.5s of silence
#define MAX_RECORDING_MS   10000 // Maximum recording length

// === Wake Word (future) ===
#define WAKE_WORD_MODEL    "hey_polly.tflite"
#define WAKE_WORD_THRESHOLD 0.5

#endif // CONFIG_H
