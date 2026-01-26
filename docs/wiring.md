# Polly Connect - Wiring Guide

## Components

| Component | Purpose | Link |
|-----------|---------|------|
| ESP32-WROOM-32 | Main microcontroller | DevKit board |
| INMP441 | I2S digital microphone | Audio input |
| MAX98357A | I2S amplifier | Audio output |
| 4Ω/8Ω Speaker | Sound output | 3W recommended |

## Wiring Diagram

```
                    ┌─────────────────┐
                    │   ESP32-WROOM   │
                    │                 │
INMP441             │                 │             MAX98357A
┌──────┐            │                 │            ┌──────────┐
│ VDD  │────────────┤ 3.3V            │            │          │
│ GND  │────────────┤ GND         GND ├────────────┤ GND      │
│ SD   │────────────┤ GPIO32          │            │          │
│ WS   │────────────┤ GPIO25          │            │          │
│ SCK  │────────────┤ GPIO33      5V  ├────────────┤ VIN      │
│ L/R  │────────────┤ GND             │            │          │
└──────┘            │            GPIO22├────────────┤ DIN      │
                    │            GPIO26├────────────┤ BCLK     │
                    │            GPIO21├────────────┤ LRC      │
                    │                 │            └────┬─────┘
                    └─────────────────┘                 │
                                                   ┌────┴────┐
                                                   │ Speaker │
                                                   │  4-8Ω   │
                                                   └─────────┘
```

## Detailed Connections

### INMP441 Microphone → ESP32

| INMP441 Pin | ESP32 Pin | Description |
|-------------|-----------|-------------|
| VDD | 3.3V | Power (3.3V only!) |
| GND | GND | Ground |
| SD | GPIO 32 | Serial Data (audio out) |
| WS | GPIO 25 | Word Select (L/R clock) |
| SCK | GPIO 33 | Serial Clock |
| L/R | GND | Left channel select |

**Note:** Connect L/R to GND for left channel, or 3.3V for right channel.

### MAX98357A Amplifier → ESP32

| MAX98357A Pin | ESP32 Pin | Description |
|---------------|-----------|-------------|
| VIN | 5V | Power (can use 3.3V but quieter) |
| GND | GND | Ground |
| DIN | GPIO 22 | Audio Data In |
| BCLK | GPIO 26 | Bit Clock |
| LRC | GPIO 21 | Left/Right Clock |
| GAIN | (see below) | Volume control |
| SD | (see below) | Shutdown (leave unconnected) |

**GAIN Pin Options:**
- Unconnected: 9dB gain (default)
- Connected to GND: 12dB gain
- Connected to VIN: 15dB gain

### Speaker → MAX98357A

Connect speaker wires to the + and - terminals on the MAX98357A board.
- 4Ω speakers: louder but more power draw
- 8Ω speakers: quieter but safer for battery operation

## Breadboard Layout

```
     1   5   10  15  20  25  30
   ┌─────────────────────────────┐
 A │                             │
 B │     ┌─────────────────┐     │
 C │     │    ESP32        │     │
 D │     │    DevKit       │     │
 E │     │                 │     │
 F │     └─────────────────┘     │
 G │                             │
 H │  ┌───────┐     ┌─────────┐  │
 I │  │INMP441│     │MAX98357A│  │
 J │  └───────┘     └─────────┘  │
   └─────────────────────────────┘
     Power rails on sides
```

## Power Considerations

### USB Power (Development)
- Connect ESP32 via USB to computer
- Provides 5V to ESP32 and amp
- 500mA typically sufficient

### Battery Power (Portable)
- Use 3.7V LiPo + boost converter to 5V
- Or use USB power bank
- Expect 200-400mA during active listening/playback

## Testing Steps

### 1. Test ESP32 First
```cpp
// Minimal test - just blink LED
void setup() {
  pinMode(2, OUTPUT);  // Built-in LED on most boards
}
void loop() {
  digitalWrite(2, HIGH);
  delay(500);
  digitalWrite(2, LOW);
  delay(500);
}
```

### 2. Test Microphone
```cpp
// Print audio levels to Serial
void loop() {
  int16_t sample;
  size_t bytesRead;
  i2s_read(I2S_NUM_0, &sample, sizeof(sample), &bytesRead, portMAX_DELAY);
  Serial.println(sample);
  delay(10);
}
```

### 3. Test Speaker
```cpp
// Play a tone
playTone(440, 500);  // 440Hz for 500ms
```

### 4. Test Full Loop
Send 'r' via Serial Monitor to trigger recording, speak, verify response.

## Troubleshooting

### No Audio from Microphone
1. Check VDD is 3.3V (not 5V!)
2. Verify L/R is connected to GND
3. Check SD/WS/SCK connections
4. Try swapping WS and SCK (some boards have different labeling)

### No Sound from Speaker
1. Check VIN is getting power
2. Verify BCLK/LRC/DIN connections
3. Try connecting GAIN to GND for more volume
4. Test with a known working audio file

### Crackling/Noise
1. Add 10µF capacitor between VIN and GND on amp
2. Keep mic wires short
3. Separate mic and speaker wiring
4. Use shielded cables for longer runs

### ESP32 Crashes/Resets
1. Insufficient power - use powered USB hub
2. Check for short circuits
3. Verify no 5V going to 3.3V pins

## Pin Customization

If you need different pins, edit `firmware/polly-esp32/config.h`:

```cpp
// Microphone pins
#define I2S_MIC_SERIAL_CLOCK   33  // Change these
#define I2S_MIC_WORD_SELECT    25
#define I2S_MIC_SERIAL_DATA    32

// Speaker pins
#define I2S_SPK_SERIAL_CLOCK   26  // Change these
#define I2S_SPK_WORD_SELECT    21
#define I2S_SPK_SERIAL_DATA    22
```

**Valid I2S pins on ESP32:**
- Most GPIOs work, but avoid:
  - GPIO 6-11 (flash)
  - GPIO 34-39 (input only)
