/**
 * Polly Connect - ESP32 Firmware
 * 
 * Voice assistant client that:
 * 1. Listens for wake word "Hey Polly"
 * 2. Captures audio via I2S microphone
 * 3. Streams audio to cloud server via WebSocket
 * 4. Plays back TTS response via I2S speaker
 * 
 * Hardware:
 * - ESP32-WROOM-32
 * - INMP441 I2S Microphone
 * - MAX98357A I2S Amplifier + Speaker
 */

#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <base64.h>
#include "config.h"
#include "audio_capture.h"
#include "audio_playback.h"

// State machine
enum State {
  STATE_IDLE,           // Waiting for wake word
  STATE_LISTENING,      // Recording user speech
  STATE_PROCESSING,     // Waiting for server response
  STATE_PLAYING         // Playing TTS response
};

State currentState = STATE_IDLE;

// WebSocket client
WebSocketsClient webSocket;
bool wsConnected = false;

// Audio buffers
#define AUDIO_BUFFER_SIZE 32000  // ~2 seconds at 16kHz
uint8_t audioBuffer[AUDIO_BUFFER_SIZE];
size_t audioBufferPos = 0;

// Timing
unsigned long lastAudioTime = 0;
unsigned long recordingStartTime = 0;
const unsigned long SILENCE_TIMEOUT_MS = 1500;  // End recording after 1.5s silence
const unsigned long MAX_RECORDING_MS = 10000;   // Max 10 second recording

// Forward declarations
void webSocketEvent(WStype_t type, uint8_t* payload, size_t length);
void connectWiFi();
void sendAudioChunk();
void processResponse(const char* json);


void setup() {
  Serial.begin(115200);
  Serial.println("\n\n=== Polly Connect ===");
  Serial.println("Initializing...");
  
  // Initialize audio hardware
  if (!initMicrophone()) {
    Serial.println("ERROR: Failed to initialize microphone!");
    while (1) delay(1000);
  }
  Serial.println("Microphone initialized");
  
  if (!initSpeaker()) {
    Serial.println("ERROR: Failed to initialize speaker!");
    while (1) delay(1000);
  }
  Serial.println("Speaker initialized");
  
  // Play startup sound
  playTone(1000, 100);
  delay(100);
  playTone(1500, 100);
  
  // Connect to WiFi
  connectWiFi();
  
  // Connect to WebSocket server
  Serial.printf("Connecting to server: %s:%d\n", SERVER_HOST, SERVER_PORT);
  webSocket.begin(SERVER_HOST, SERVER_PORT, SERVER_PATH);
  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(5000);
  
  Serial.println("Setup complete. Waiting for wake word...");
}


void loop() {
  // Handle WebSocket
  webSocket.loop();
  
  switch (currentState) {
    case STATE_IDLE:
      // TODO: Wake word detection
      // For now, use button or serial command to trigger
      if (Serial.available()) {
        char c = Serial.read();
        if (c == 'r' || c == 'R') {
          startRecording();
        }
      }
      break;
      
    case STATE_LISTENING:
      recordAudio();
      break;
      
    case STATE_PROCESSING:
      // Waiting for server response
      break;
      
    case STATE_PLAYING:
      // Playback handled in response callback
      break;
  }
}


void connectWiFi() {
  Serial.printf("Connecting to WiFi: %s\n", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected!");
    Serial.printf("IP address: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\nWiFi connection failed!");
  }
}


void webSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_DISCONNECTED:
      Serial.println("WebSocket disconnected");
      wsConnected = false;
      break;
      
    case WStype_CONNECTED:
      Serial.println("WebSocket connected");
      wsConnected = true;
      
      // Send connect message
      {
        StaticJsonDocument<200> doc;
        doc["event"] = "connect";
        doc["device_id"] = DEVICE_ID;
        String json;
        serializeJson(doc, json);
        webSocket.sendTXT(json);
      }
      break;
      
    case WStype_TEXT:
      Serial.printf("Received: %s\n", payload);
      processResponse((const char*)payload);
      break;
      
    case WStype_ERROR:
      Serial.println("WebSocket error");
      break;
      
    default:
      break;
  }
}


void startRecording() {
  if (!wsConnected) {
    Serial.println("Not connected to server!");
    playTone(200, 500);  // Error tone
    return;
  }
  
  Serial.println("Starting recording...");
  playTone(800, 100);  // Beep to indicate listening
  
  currentState = STATE_LISTENING;
  audioBufferPos = 0;
  recordingStartTime = millis();
  lastAudioTime = millis();
}


void recordAudio() {
  // Read audio samples
  int16_t samples[256];
  size_t bytesRead = readMicrophoneSamples(samples, 256);
  
  if (bytesRead > 0) {
    // Calculate audio level for silence detection
    int32_t level = 0;
    for (int i = 0; i < bytesRead / 2; i++) {
      level += abs(samples[i]);
    }
    level /= (bytesRead / 2);
    
    // Check for audio activity
    if (level > SILENCE_THRESHOLD) {
      lastAudioTime = millis();
    }
    
    // Add to buffer
    size_t bytesToCopy = min(bytesRead, AUDIO_BUFFER_SIZE - audioBufferPos);
    memcpy(audioBuffer + audioBufferPos, samples, bytesToCopy);
    audioBufferPos += bytesToCopy;
    
    // Stream chunk to server
    if (audioBufferPos >= CHUNK_SIZE) {
      sendAudioChunk();
    }
  }
  
  // Check for end conditions
  unsigned long elapsed = millis() - recordingStartTime;
  unsigned long silenceTime = millis() - lastAudioTime;
  
  if (silenceTime > SILENCE_TIMEOUT_MS || elapsed > MAX_RECORDING_MS) {
    stopRecording();
  }
}


void sendAudioChunk() {
  if (!wsConnected || audioBufferPos == 0) return;
  
  // Base64 encode
  String b64 = base64::encode(audioBuffer, audioBufferPos);
  
  // Send via WebSocket
  StaticJsonDocument<48000> doc;  // Large enough for base64 audio
  doc["event"] = "audio";
  doc["data"] = b64;
  
  String json;
  serializeJson(doc, json);
  webSocket.sendTXT(json);
  
  // Reset buffer
  audioBufferPos = 0;
}


void stopRecording() {
  Serial.println("Stopping recording...");
  
  // Send any remaining audio
  if (audioBufferPos > 0) {
    sendAudioChunk();
  }
  
  // Signal end of stream
  StaticJsonDocument<100> doc;
  doc["event"] = "end_stream";
  String json;
  serializeJson(doc, json);
  webSocket.sendTXT(json);
  
  currentState = STATE_PROCESSING;
  playTone(600, 100);  // Processing beep
}


void processResponse(const char* jsonStr) {
  StaticJsonDocument<48000> doc;
  DeserializationError error = deserializeJson(doc, jsonStr);
  
  if (error) {
    Serial.printf("JSON parse error: %s\n", error.c_str());
    currentState = STATE_IDLE;
    return;
  }
  
  const char* event = doc["event"];
  
  if (strcmp(event, "connected") == 0) {
    Serial.println("Server acknowledged connection");
    
  } else if (strcmp(event, "response") == 0) {
    // Got response from server
    const char* text = doc["text"];
    const char* audioB64 = doc["audio"];
    
    Serial.printf("Response: %s\n", text);
    
    if (audioB64 && strlen(audioB64) > 0) {
      // Decode and play audio
      currentState = STATE_PLAYING;
      
      // Decode base64
      int decodedLen = base64_dec_len((char*)audioB64, strlen(audioB64));
      uint8_t* audioData = (uint8_t*)malloc(decodedLen);
      
      if (audioData) {
        base64_decode((char*)audioData, (char*)audioB64, strlen(audioB64));
        playAudio(audioData, decodedLen);
        free(audioData);
      }
    }
    
    currentState = STATE_IDLE;
    
  } else if (strcmp(event, "error") == 0) {
    const char* msg = doc["message"];
    Serial.printf("Server error: %s\n", msg);
    playTone(200, 300);  // Error tone
    currentState = STATE_IDLE;
  }
}
