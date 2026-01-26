# Polly Connect API Reference

Base URL: `http://localhost:8000` (development) or `https://api.polly.io` (production)

## REST Endpoints

### Health Check

```
GET /health
```

**Response:**
```json
{"status": "healthy"}
```

---

### Process Natural Language Command

```
POST /api/command
Content-Type: application/json
```

**Request:**
```json
{
  "text": "the wrench is in the left drawer"
}
```

**Response:**
```json
{
  "intent": "store",
  "confidence": 0.85,
  "input": "the wrench is in the left drawer",
  "message": "Stored: wrench → left drawer",
  "item_id": 1
}
```

**Intents:**
- `store` - Storing item location
- `retrieve_item` - Finding where an item is
- `retrieve_location` - Listing items in a location
- `delete` - Removing an item
- `list_all` - List all items
- `help` - Show help
- `unknown` - Unrecognized command

---

### List Items

```
GET /api/items
GET /api/items?search=wrench
GET /api/items?location=drawer
```

**Response:**
```json
{
  "items": [
    {
      "id": 1,
      "item": "wrench",
      "location": "left drawer",
      "context": "behind the screwdrivers",
      "created_at": "2024-01-15T10:30:00",
      "updated_at": "2024-01-15T10:30:00"
    }
  ],
  "count": 1
}
```

---

### Add Item Directly

```
POST /api/items
Content-Type: application/json
```

**Request:**
```json
{
  "item": "wrench",
  "location": "left drawer",
  "context": "behind the screwdrivers"
}
```

**Response:**
```json
{
  "id": 1,
  "item": "wrench",
  "location": "left drawer",
  "context": "behind the screwdrivers",
  "message": "Item stored"
}
```

---

### Delete Item

```
DELETE /api/items/{item_id}
```

**Response:**
```json
{
  "message": "Item deleted",
  "id": 1
}
```

---

### List Locations

```
GET /api/locations
```

**Response:**
```json
{
  "locations": ["left drawer", "pegboard", "red bin"],
  "count": 3
}
```

---

### Get Items in Location

```
GET /api/locations/{location_name}
```

**Response:**
```json
{
  "location": "left drawer",
  "items": [...],
  "count": 3
}
```

---

### Get Statistics

```
GET /api/stats
```

**Response:**
```json
{
  "total_items": 15,
  "unique_locations": 5,
  "recent": [
    {"item": "wrench", "location": "left drawer"},
    {"item": "hammer", "location": "pegboard"}
  ]
}
```

---

### Export Data

```
GET /api/export
```

**Response:**
```json
{
  "version": "1.0",
  "items": [...],
  "count": 15
}
```

---

### Import Data

```
POST /api/import
Content-Type: application/json
```

**Request:**
```json
{
  "version": "1.0",
  "items": [
    {"item": "wrench", "location": "drawer", "context": null}
  ]
}
```

**Response:**
```json
{
  "message": "Imported 1 items",
  "count": 1
}
```

---

## WebSocket API

### Connect

```
WebSocket: ws://localhost:8000/api/audio/stream
```

### Protocol

#### 1. Device Connects

**Send:**
```json
{
  "event": "connect",
  "device_id": "polly001"
}
```

**Receive:**
```json
{
  "event": "connected",
  "message": "Ready to receive audio"
}
```

#### 2. Stream Audio

**Send (multiple times):**
```json
{
  "event": "audio",
  "data": "<base64 encoded PCM audio>"
}
```

Audio format:
- 16-bit PCM
- 16kHz sample rate
- Mono
- Chunk size: ~4KB recommended

#### 3. End Stream

**Send:**
```json
{
  "event": "end_stream"
}
```

**Receive:**
```json
{
  "event": "response",
  "text": "The wrench is in the left drawer",
  "audio": "<base64 encoded WAV>",
  "intent": "retrieve_item",
  "transcription": "where is the wrench"
}
```

#### 4. Keep-Alive

**Send:**
```json
{"event": "ping"}
```

**Receive:**
```json
{"event": "pong"}
```

---

## Device Management

### Register Device

```
POST /api/devices/register
Content-Type: application/json
```

**Request:**
```json
{
  "device_id": "polly001",
  "firmware_version": "0.1.0",
  "hardware_version": "esp32-wroom"
}
```

**Response:**
```json
{
  "message": "Device registered",
  "device_id": "polly001",
  "config": {
    "wake_word_sensitivity": 0.5,
    "silence_timeout_ms": 1000,
    "sample_rate": 16000
  }
}
```

---

### List Devices

```
GET /api/devices/
```

**Response:**
```json
{
  "devices": [
    {
      "device_id": "polly001",
      "firmware_version": "0.1.0",
      "registered_at": "2024-01-15T10:00:00",
      "last_seen": "2024-01-15T10:30:00",
      "status": "online"
    }
  ],
  "count": 1
}
```

---

### Device Heartbeat

```
POST /api/devices/{device_id}/heartbeat
```

**Response:**
```json
{"status": "ok"}
```

---

### Get Device Config

```
GET /api/devices/{device_id}/config
```

**Response:**
```json
{
  "wake_word_sensitivity": 0.5,
  "silence_timeout_ms": 1000,
  "sample_rate": 16000,
  "server_url": null
}
```

---

## Error Responses

All endpoints return errors in this format:

```json
{
  "detail": "Error message here"
}
```

HTTP status codes:
- `400` - Bad request (invalid input)
- `404` - Not found
- `500` - Server error

---

## Example: Python Client

```python
import requests
import websocket
import json
import base64

# REST API example
response = requests.post(
    "http://localhost:8000/api/command",
    json={"text": "where is the wrench"}
)
print(response.json())

# WebSocket example
ws = websocket.create_connection("ws://localhost:8000/api/audio/stream")
ws.send(json.dumps({"event": "connect", "device_id": "test"}))
print(ws.recv())

# Send audio
with open("audio.raw", "rb") as f:
    audio = f.read()
ws.send(json.dumps({
    "event": "audio",
    "data": base64.b64encode(audio).decode()
}))
ws.send(json.dumps({"event": "end_stream"}))
response = json.loads(ws.recv())
print(response["text"])
ws.close()
```

---

## Example: JavaScript Client

```javascript
// REST API
const response = await fetch('http://localhost:8000/api/command', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({text: 'where is the wrench'})
});
const data = await response.json();
console.log(data);

// WebSocket
const ws = new WebSocket('ws://localhost:8000/api/audio/stream');
ws.onopen = () => {
  ws.send(JSON.stringify({event: 'connect', device_id: 'web'}));
};
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data);
};
```
