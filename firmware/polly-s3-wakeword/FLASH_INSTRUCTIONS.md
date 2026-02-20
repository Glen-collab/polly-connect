# Polly S3 Wake Word - Flash Instructions

## What This Does
- ESP32-S3 listens continuously for "Hi ESP" wake word (placeholder)
- On detection: beep → record your speech → send to Polly server → play response
- Wake word runs 100% locally on the chip (no cloud needed for detection)
- Custom "Hey Polly" wake word will replace "Hi ESP" after training

## Hardware Wiring

### INMP441 Microphone
| INMP441 Pin | ESP32-S3 Pin |
|-------------|-------------|
| VDD         | 3.3V        |
| GND         | GND         |
| SCK         | GPIO6       |
| WS          | GPIO5       |
| SD          | GPIO4       |
| L/R         | GND         |

### MAX98357A Speaker Amp
| MAX98357A Pin | ESP32-S3 Pin |
|---------------|-------------|
| VIN           | 5V          |
| GND           | GND         |
| BCLK          | GPIO12      |
| LRC           | GPIO11      |
| DIN           | GPIO10      |

### Speaker
- Connect speaker wires to + and - on MAX98357A

## Step 1: Install ESP-IDF (One Time)

1. Download the **ESP-IDF v5.4.x Windows Installer** from:
   https://dl.espressif.com/dl/esp-idf/

2. Run the installer:
   - Install to default `C:\Espressif\`
   - Select ESP-IDF v5.4.x
   - Check ALL chip targets (especially ESP32-S3)
   - Let it install everything (Python, Git, CMake, toolchains)

3. After install, you'll have a new shortcut:
   **"ESP-IDF 5.4 CMD"** in your Start Menu
   USE THIS for all commands below (not regular cmd/PowerShell)

## Step 2: Plug In ESP32-S3

1. Connect ESP32-S3 to your PC via USB cable
2. Check which COM port it's on:
   - Open Device Manager → Ports (COM & LPT)
   - Look for "USB-SERIAL" or "CP210x" or "CH340"
   - Note the COM number (e.g., COM3)

   If no COM port shows up, you may need a driver:
   - CP2102: https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers
   - CH340: https://www.wch-ic.com/downloads/CH341SER_EXE.html

## Step 3: Build

Open **ESP-IDF 5.4 CMD** from Start Menu, then:

```
cd C:\Users\big_g\Desktop\polly-connect\firmware\polly-s3-wakeword

idf.py set-target esp32s3

idf.py build
```

First build takes 5-10 minutes (downloads ESP-SR models, compiles everything).
Subsequent builds are much faster.

## Step 4: Flash

```
idf.py -p COM3 flash
```

Replace COM3 with your actual COM port from Step 2.

If it says "failed to connect":
1. Hold the BOOT button on the ESP32-S3
2. Press and release the RESET button
3. Release the BOOT button
4. Try the flash command again

## Step 5: Monitor (See Serial Output)

```
idf.py -p COM3 monitor
```

You should see:
```
=== Polly Connect - ESP32-S3 Wake Word ===
Microphone initialized (INMP441 on GPIO 5/4/6)
Speaker initialized (MAX98357A on GPIO 15/16/17)
WiFi connected! IP: 192.168.x.x
WakeNet initialized - listening for 'Hi ESP'
Say 'Hi ESP' to activate!
```

When you say "Hi ESP", you should see:
```
*** WAKE WORD DETECTED! ***
Recording started...
Silence detected - stopping recording
Recorded 24000 samples (1.5 seconds)
Sending 48000 bytes to server...
```

Press Ctrl+] to exit the monitor.

## Step 6: Build + Flash + Monitor (All at Once)

For convenience, you can do all three in one command:

```
idf.py -p COM3 flash monitor
```

## Troubleshooting

### "No COM port found"
- Try a different USB cable (some are charge-only)
- Try the other USB port on the ESP32-S3 (some boards have two)
- Install the USB driver (see Step 2)

### "Failed to connect to ESP32-S3"
- Use the BOOT + RESET button combo (see Step 4)
- Make sure you're using USB, not UART

### "WiFi connection failed"
- Edit `main/main.c` line 60-61 with your home WiFi credentials
- Rebuild and reflash

### "No wake word model found"
- Make sure `sdkconfig.defaults` has `CONFIG_SR_WN_WN9_HIESP=y`
- Delete the `build/` folder and rebuild: `idf.py fullclean && idf.py build`

### Mic not working (no audio levels)
- Check wiring: SCK→GPIO5, WS→GPIO4, SD→GPIO6, L/R→GND
- Make sure INMP441 gets 3.3V (NOT 5V!)
- Try swapping L/R pin to 3.3V (right channel) and change code

## Before Flashing: Edit Your WiFi

Open `main/main.c` and update lines 60-61 with your HOME WiFi:

```c
#define WIFI_SSID      "Your_Home_WiFi"
#define WIFI_PASSWORD   "Your_Home_Password"
```

Also update line 64 with your PC's IP address on your home network:

```c
#define SERVER_HOST     "192.168.1.100"
```

To find your PC's IP: open CMD and type `ipconfig`

## What's Next

After confirming wake word works with "Hi ESP":
1. Train custom "Hey Polly" model using your recorded samples
2. Swap the model file
3. Design PCB in KiCad with these exact pin assignments
