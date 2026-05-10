# Polly PCB - Layout Status

## Current State: SCHEMATIC VERIFIED — Ready for PCB Routing

**KiCad version:** 9.0.7
**Board size:** ~70mm x 50mm (Edge.Cuts rectangle)
**Layers:** 2-layer (F.Cu front, B.Cu back)
**Schematic verified:** 2026-03-03
**Designer:** Fiverr contractor (schematic fixes applied, reviewed and confirmed)

## Schematic: VERIFIED COMPLETE
All schematic errors from initial review have been fixed. Pin assignments confirmed to match the working breadboard prototype. Ready for PCB layout/routing.

## Components

| Ref | Component | Value/Footprint | Purpose |
|-----|-----------|-----------------|---------|
| U2 | ESP32-S3-WROOM-1 | PCM_Espressif | Main MCU |
| U1 | AMS1117-3.3 | SOT-223 | 5V → 3.3V regulator |
| J1 | USB-C Receptacle (16P) | HRO TYPE-C-31-M-12 | Power + USB data |
| J2 | 5-pin header (INMP441 mic) | PinHeader 2.54mm | Microphone breakout |
| J5 | 5-pin header (MAX98357A amp) | PinHeader 2.54mm | Amplifier breakout |
| J4 | 2-pin header (LED) | PinHeader 2.54mm | Status LED |
| SW1 | Push button (BOOT) | PTS645 SMD | GPIO0 → GND (flash mode) |
| SW2 | Push button (RESET) | PTS645 SMD | EN → GND (reset) |
| C1 | 100nF | 0805 SMD | Regulator output decoupling |
| C2 | 10uF | 0805 SMD | Regulator output bulk bypass |
| C3 | 100nF | 0805 SMD | ESP32 decoupling |
| C4 | 10uF | 0805 SMD | Regulator input filter |
| R1 | 10kΩ | 0805 SMD | EN pull-up |
| R2 | 5.1kΩ | 0805 SMD | USB CC2 pull-down to GND |
| R3 | 5.1kΩ | 0805 SMD | USB CC1 pull-down to GND |
| R4 | 330Ω | 0805 SMD | LED current limiter (GPIO48) |

## Verified Net List

```
USB-C (J1):
  VBUS (A4/A9/B4/B9) → +5V rail → U1 pin 3 (VI) → C4
  GND (A1/A12/B1/B12) → GND net
  CC1 (A5) → R3 (5.1kΩ) → GND
  CC2 (B5) → R2 (5.1kΩ) → GND
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
  Pin 3 (EN) → R1 (10kΩ) → +3.3V, also → SW2 → GND
  Pin 4 (GPIO4) → J2 pin 3 (mic SD)
  Pin 5 (GPIO5) → J2 pin 2 (mic WS)
  Pin 6 (GPIO6) → J2 pin 1 (mic SCK)
  Pin 13 (GPIO19) → USB D-
  Pin 14 (GPIO20) → USB D+
  Pin 18 (GPIO10) → J5 pin 3 (amp DIN)
  Pin 19 (GPIO11) → J5 pin 2 (amp LRC)
  Pin 20 (GPIO12) → J5 pin 1 (amp BCLK)
  Pin 25 (GPIO48) → R4 (330Ω) → J4 pin 1 (LED)
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

LED Header (J4):
  Pin 1 → R4 (330Ω) → GPIO48
  Pin 2 → GND

Capacitors:
  C1 (100nF): +3.3V → GND (near U1)
  C2 (10uF): +3.3V → GND (near U1)
  C3 (100nF): +3.3V → GND (near U2)
  C4 (10uF): +5V → GND (near U1 input)

Buttons:
  SW1 (BOOT): GPIO0 → GND when pressed
  SW2 (RESET): EN → GND when pressed
```

## PCB Routing Notes (for designer)

### Placement Guidelines
- U1 (regulator) near J1 (USB-C) — short power path
- C1, C2 close to U1 output
- C4 close to U1 input or J1
- C3 close to U2 pin 2 (3V3)
- ESP32-S3 antenna must overhang board edge or have ground clearance (no copper/ground pour under antenna)
- SW1 (BOOT) and SW2 (RESET) accessible from board edge

### After Routing
1. Add ground pour on both F.Cu and B.Cu (net = GND)
2. Keep antenna area clear of copper
3. Run DRC — should be clean except cosmetic silkscreen warnings
4. Fix any silkscreen overlaps

## ESP32-S3 Pin Assignments (from working prototype)

| Function | GPIO | ESP32-S3 Module Pin | Header |
|----------|------|---------------------|--------|
| INMP441 SCK | GPIO 6 | Pin 6 | J2 Pin 1 |
| INMP441 WS | GPIO 5 | Pin 5 | J2 Pin 2 |
| INMP441 SD | GPIO 4 | Pin 4 | J2 Pin 3 |
| MAX98357A BCLK | GPIO 12 | Pin 20 | J5 Pin 1 |
| MAX98357A LRC | GPIO 11 | Pin 19 | J5 Pin 2 |
| MAX98357A DIN | GPIO 10 | Pin 18 | J5 Pin 3 |
| Status LED | GPIO 48 | Pin 25 | J4 Pin 1 (via R4) |
| Boot button | GPIO 0 | Pin 27 | SW1 → GND |
| EN/Reset | EN | Pin 3 | R1 pull-up + SW2 → GND |
| USB D- | GPIO 19 | Pin 13 | J1 D- |
| USB D+ | GPIO 20 | Pin 14 | J1 D+ |

## Files
- `polly_pcb.kicad_pro` — project settings
- `polly_pcb.kicad_sch` — schematic (verified complete)
- `polly_pcb.kicad_pcb` — PCB layout (needs re-routing after schematic changes)
- `SCHEMATIC-FIXES.md` — original fix list sent to designer (20 fixes)
- `DESIGNER-REVIEW.md` — review of designer's first revision
