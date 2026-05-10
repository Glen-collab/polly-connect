# Polly PCB Schematic Fix List

**Project:** Polly Connect — ESP32-S3 Voice Companion Board
**Date:** 2026-03-02
**KiCad Version:** 9.0.7
**Schematic File:** `polly_pcb.kicad_sch`

This document lists all schematic errors found during review, organized by priority. The working prototype pinout (breadboard) is the source of truth for all GPIO assignments.

---

## Reference: Working Prototype Pin Assignments

| Function | GPIO | ESP32-S3-WROOM-1 Module Pin |
|----------|------|-----------------------------|
| INMP441 SCK (mic clock) | GPIO 6 | Pin 6 |
| INMP441 WS (mic word select) | GPIO 5 | Pin 5 |
| INMP441 SD (mic data out) | GPIO 4 | Pin 4 |
| MAX98357A BCLK (amp bit clock) | GPIO 12 | Pin 20 |
| MAX98357A LRC (amp left/right) | GPIO 11 | Pin 19 |
| MAX98357A DIN (amp data in) | GPIO 10 | Pin 18 |
| Status LED | GPIO 48 | Pin 25 |
| Boot Button | GPIO 0 | Pin 27 |
| EN / Reset | EN | Pin 3 |
| USB D- | GPIO 19 | Pin 13 |
| USB D+ | GPIO 20 | Pin 14 |

---

## PRIORITY 1 — Power (will destroy components if not fixed)

### Fix 1.1: ESP32 3V3 and GND are swapped

**Problem:** U2 pin 2 (3V3 power input) is connected to the GND net. U2 pin 1 (GND) is connected to the +3.3V net. Building this as-is will destroy the ESP32 module.

**Fix:** Swap the two net connections on the ESP32:
- U2 **Pin 1** (GND) → connect to **GND** net
- U2 **Pin 2** (3V3) → connect to **+3.3V** net
- U2 **Pin 40** (GND) → connect to **GND** net
- U2 **Pin 41** (GND) → connect to **GND** net

---

### Fix 1.2: USB-C VBUS not connected to voltage regulator

**Problem:** The USB-C VBUS pins (J1 pins A4, A9, B4, B9) are not connected to anything useful. Instead, J1 pin B8 (SBU2 — a sideband pin, NOT a power pin) is mistakenly routed to U1 input.

**Fix:**
- Disconnect J1 pin B8 (SBU2) from U1 input — leave SBU2 unconnected
- Connect J1 VBUS pins (A4/A9/B4/B9) → U1 pin 3 (VI, regulator input)
- This is the +5V rail from USB

---

### Fix 1.3: AMS1117 regulator GND pin is floating

**Problem:** U1 pin 1 (GND) has no connection. The regulator cannot function without a ground return path.

**Fix:** Connect U1 **pin 1** (GND) → **GND** net

---

### Fix 1.4: USB-C GND pins isolated from board GND

**Problem:** J1 GND pins (A1, A12, B1, B12) connect only to each other but have no wire to the rest of the circuit's GND net.

**Fix:** Connect J1 GND pins → **GND** net (one wire from the group to the GND rail is sufficient)

---

### Fix 1.5: USB-C shield pin

**Problem:** J1 shield pin (S1) is floating.

**Fix:** Connect J1 **S1** (shield) → **GND** net

---

## PRIORITY 2 — USB-C CC Pull-Downs (required for power delivery)

### Fix 2.1: CC1 and CC2 pull-down resistors not connected

**Problem:** USB-C pins CC1 (J1 pin A5) and CC2 (J1 pin B5) are both completely isolated. Without 5.1k ohm pull-down resistors to GND, the USB host will not recognize the device and will not supply power.

R2 and R3 exist in the schematic but are not wired to CC1/CC2 or GND.

**Fix:**
- Connect J1 **pin A5** (CC1) → **R3 pin 1**
- Connect R3 **pin 2** → **GND**
- Connect J1 **pin B5** (CC2) → **R2 pin 1**
- Connect R2 **pin 2** → **GND**

---

### Fix 2.2: CC pull-down resistor values are wrong

**Problem:** R2 and R3 are labeled "5.1" which means 5.1 ohms. The USB-C specification requires 5.1 kilohms (5100 ohms).

**Fix:** Change both R2 and R3 values from **"5.1"** to **"5.1k"** (5100 ohms)

---

## PRIORITY 3 — USB Data Lines (required for programming/flashing)

### Fix 3.1: USB D+ connected to wrong GPIO

**Problem:** USB D+ (J1 pin A6) is routed to U2 GPIO38 (module pin 31). On the ESP32-S3, the native USB D+ pin is GPIO20 (module pin 14). GPIO38 has no USB function.

Also, J1 pin B7 (D- on the B side) is incorrectly shorted to the same net as D+.

**Fix:**
- Disconnect J1 pin A6 (D+) from U2 pin 31 (GPIO38)
- Connect J1 pin A6 (D+) → U2 **pin 14** (GPIO20)
- For USB 2.0: short J1 pin B6 to J1 pin A6 (both D+ sides together)

---

### Fix 3.2: USB D- connected to wrong GPIO

**Problem:** USB D- (J1 pin A7) is routed to U2 GPIO45 (module pin 26). The native USB D- pin is GPIO19 (module pin 13).

**Fix:**
- Disconnect J1 pin A7 (D-) from U2 pin 26 (GPIO45)
- Connect J1 pin A7 (D-) → U2 **pin 13** (GPIO19)
- For USB 2.0: short J1 pin B7 to J1 pin A7 (both D- sides together)

---

## PRIORITY 4 — Button and Control Pin Fixes

### Fix 4.1: Boot button on wrong GPIO

**Problem:** SW1 connects to U2 GPIO18 (module pin 11). The ESP32-S3 boot mode pin is GPIO0 (module pin 27). GPIO0 must be held LOW during reset to enter download/flash mode.

**Fix:**
- Disconnect SW1 pin 2 from U2 pin 11 (GPIO18)
- Connect SW1 **pin 1** → **GND**
- Connect SW1 **pin 2** → U2 **pin 27** (GPIO0)

Note: The boot button should pull GPIO0 to GND when pressed. A 10k pull-up on GPIO0 to 3.3V is recommended but the ESP32-S3 has an internal pull-up on GPIO0, so it is optional.

---

### Fix 4.2: Reset button not connected

**Problem:** SW2 pin 2 is floating. It should connect to the ESP32 EN (enable/reset) pin to allow manual reset.

**Fix:**
- Connect SW2 **pin 1** → **GND**
- Connect SW2 **pin 2** → U2 **pin 3** (EN)

Pressing SW2 pulls EN low, resetting the ESP32.

---

### Fix 4.3: EN pull-up resistor on wrong pin

**Problem:** R1 (10k ohm) connects between +3.3V and U2 GPIO37 (module pin 30). It should connect to the EN pin instead. EN requires an external pull-up to keep the chip running.

**Fix:**
- Disconnect R1 pin 2 from U2 pin 30 (GPIO37)
- Connect R1 **pin 1** → **+3.3V**
- Connect R1 **pin 2** → U2 **pin 3** (EN)

This keeps EN high (chip running) and SW2 can pull it low to reset.

---

### Fix 4.4: LED resistor on wrong GPIO

**Problem:** R4 (330 ohm) connects to U2 GPIO43/TXD (module pin 37). The status LED should be on GPIO48 (module pin 25), which is the onboard RGB LED pin on most ESP32-S3 dev boards and matches the firmware.

**Fix:**
- Disconnect R4 pin 2 from U2 pin 37 (GPIO43)
- Connect R4 **pin 2** → U2 **pin 25** (GPIO48)
- R4 pin 1 should connect to the LED anode (or +3.3V if driving LED to ground through GPIO)

---

## PRIORITY 5 — Header Power Pin Fixes

### Fix 5.1: INMP441 mic header (J2) power pins

**Problem:** J2 pin 5 is connected to +5V. The INMP441 is a 3.3V-only device (rated 1.8V to 3.3V max). Applying 5V will damage the microphone.

**Fix:**
- J2 **Pin 4** (VDD) → connect to **+3.3V** rail (AMS1117 output)
- J2 **Pin 5** (GND) → connect to **GND** net

INMP441 header pinout should be:

| J2 Pin | Signal | Net |
|--------|--------|-----|
| 1 | SCK | GPIO6 (already correct) |
| 2 | WS | GPIO5 (already correct) |
| 3 | SD | GPIO4 (already correct) |
| 4 | VDD | +3.3V |
| 5 | GND | GND |

---

### Fix 5.2: MAX98357A amp header (J5) power pins

**Problem:** J5 pin 4 is connected to +3.3V and J5 pin 5 is connected to +3.3V. The MAX98357A can operate from 2.5V to 5.5V, but 5V gives significantly more speaker volume. Pin 5 should be GND, not power.

**Fix:**
- J5 **Pin 4** (VIN) → connect to **+5V** rail (VBUS, before the regulator)
- J5 **Pin 5** (GND) → connect to **GND** net

MAX98357A header pinout should be:

| J5 Pin | Signal | Net |
|--------|--------|-----|
| 1 | BCLK | GPIO12 (already correct) |
| 2 | LRC | GPIO11 (already correct) |
| 3 | DIN | GPIO10 (already correct) |
| 4 | VIN | +5V (VBUS) |
| 5 | GND | GND |

---

### Fix 5.3: Speaker output header (J4)

**Problem:** J4 (2-pin speaker output header) pins are both isolated.

**Fix:** These connect to the speaker terminals on the MAX98357A breakout board, so they may not need board-level connections. If J4 is intended as a pass-through, leave as-is or connect to J5's speaker output pins. Confirm intended use.

---

## PRIORITY 6 — Capacitor Placement Verification

Once the power net swap (Fix 1.1) is corrected, verify these capacitors are on the correct nets:

| Ref | Value | Pin 1 (+) Should Connect To | Pin 2 (-) Should Connect To | Purpose |
|-----|-------|----------------------------|----------------------------|---------|
| C1 | 100nF | +3.3V (U1 output) | GND | Regulator output decoupling |
| C2 | 10uF | +3.3V (U1 output) | GND | Regulator output bulk bypass |
| C3 | 100nF | +3.3V (near U2) | GND | ESP32 decoupling |
| C4 | 10uF | +5V (U1 input / VBUS) | GND | Regulator input filter |

Place C1 and C2 physically close to U1 (AMS1117). Place C3 close to U2 (ESP32 3V3 pin). Place C4 near the USB-C connector or U1 input.

---

## Summary: What Is Already Correct (no changes needed)

These connections are verified correct and should NOT be changed:

| Connection | Status |
|-----------|--------|
| GPIO 4 (pin 4) → J2 Pin 3 (mic SD) | CORRECT |
| GPIO 5 (pin 5) → J2 Pin 2 (mic WS) | CORRECT |
| GPIO 6 (pin 6) → J2 Pin 1 (mic SCK) | CORRECT |
| GPIO 10 (pin 18) → J5 Pin 3 (amp DIN) | CORRECT |
| GPIO 11 (pin 19) → J5 Pin 2 (amp LRC) | CORRECT |
| GPIO 12 (pin 20) → J5 Pin 1 (amp BCLK) | CORRECT |
| ESP32-S3-WROOM-1 footprint (PCM_Espressif) | CORRECT |
| AMS1117-3.3 as 5V→3.3V regulator | CORRECT |
| R1 = 10k (EN pull-up value) | CORRECT |
| R4 = 330 ohm (LED current limiter value) | CORRECT |

---

## Complete Corrected Net List

After all fixes are applied, the schematic should have these connections:

```
USB-C (J1):
  VBUS (A4/A9/B4/B9) → +5V rail → U1 pin 3 (VI) → C4 pin 1
  GND (A1/A12/B1/B12) → GND net
  CC1 (A5) → R3 (5.1k) → GND
  CC2 (B5) → R2 (5.1k) → GND
  D+ (A6/B6) → U2 pin 14 (GPIO20)
  D- (A7/B7) → U2 pin 13 (GPIO19)
  Shield (S1) → GND

AMS1117-3.3 Regulator (U1):
  Pin 3 (VI) → +5V (from VBUS)
  Pin 2 (VO) → +3.3V rail
  Pin 1 (GND) → GND

ESP32-S3-WROOM-1 (U2):
  Pin 1 (GND) → GND
  Pin 2 (3V3) → +3.3V
  Pin 3 (EN) → R1 (10k) → +3.3V, also → SW2 → GND
  Pin 4 (GPIO4) → J2 pin 3 (mic SD)
  Pin 5 (GPIO5) → J2 pin 2 (mic WS)
  Pin 6 (GPIO6) → J2 pin 1 (mic SCK)
  Pin 13 (GPIO19) → J1 D- (A7/B7)
  Pin 14 (GPIO20) → J1 D+ (A6/B6)
  Pin 18 (GPIO10) → J5 pin 3 (amp DIN)
  Pin 19 (GPIO11) → J5 pin 2 (amp LRC)
  Pin 20 (GPIO12) → J5 pin 1 (amp BCLK)
  Pin 25 (GPIO48) → R4 (330 ohm) → LED
  Pin 27 (GPIO0) → SW1 → GND
  Pin 40 (GND) → GND
  Pin 41 (GND) → GND

Mic Header (J2) — INMP441:
  Pin 1 → GPIO6 (SCK)
  Pin 2 → GPIO5 (WS)
  Pin 3 → GPIO4 (SD)
  Pin 4 → +3.3V
  Pin 5 → GND

Amp Header (J5) — MAX98357A:
  Pin 1 → GPIO12 (BCLK)
  Pin 2 → GPIO11 (LRC)
  Pin 3 → GPIO10 (DIN)
  Pin 4 → +5V (VBUS)
  Pin 5 → GND

Capacitors:
  C1 (100nF): +3.3V → GND (near U1)
  C2 (10uF): +3.3V → GND (near U1)
  C3 (100nF): +3.3V → GND (near U2)
  C4 (10uF): +5V → GND (near U1 input)

Buttons:
  SW1 (BOOT): GPIO0 → GND when pressed
  SW2 (RESET): EN → GND when pressed
```

---

## Total Fix Count

| Priority | Fixes | Category |
|----------|-------|----------|
| P1 | 5 fixes | Power and ground (board won't power on) |
| P2 | 2 fixes | USB-C CC pull-downs (no power delivery) |
| P3 | 2 fixes | USB data lines (can't flash firmware) |
| P4 | 4 fixes | Buttons and control pins |
| P5 | 3 fixes | Header power pins (component damage risk) |
| P6 | 4 verifications | Capacitor placement |
| **Total** | **20 fixes** | |
