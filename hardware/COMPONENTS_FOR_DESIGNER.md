# Polly PCB v2 — Components List for New Designer

**Purpose:** Everything a designer needs to pick parts and lay out the Polly Connect board. Paul P. (previous designer) already delivered a working layout, but his KiCad files aren't available to us — this document + the reference render in `polly-board/polly_board_v2_final.png` is the handoff. The design itself is verified against a working breadboard prototype.

**Board size:** 45 × 35 mm (width × height), 2-layer FR4, fully SMT-assembled by JLCPCB.

**End-user connections (only these are customer-facing):**
- USB-C (power + firmware flash)
- JST 2-pin (speaker wire out)
- JST 3-pin (LED wire to Polly's eyes)

No exposed pin headers. No hand soldering. UART fallback exposed as **test points along the bottom edge** only (pogo-pin probe, not a connector).

---

## BOM

All part numbers are JLCPCB LCSC codes. Verify stock right before ordering — LCSC parts rotate in and out.

| Ref | Component | LCSC | Package | Notes |
|-----|-----------|------|---------|-------|
| U1 | **ESP32-S3-WROOM-1-N16R8** | **C2913202** | SMD module | **DO NOT SUBSTITUTE.** Must be N16R8 (16 MB flash, 8 MB octal PSRAM). A previous order was substituted to N4R2, which is incompatible with the firmware. Add this as a human-readable order note to JLCPCB. |
| U2 | AMS1117-3.3 | C6186 | SOT-223 | 5V → 3.3V LDO regulator. Standard SOT-223 pinout: pin 1 = GND, pin 2 = Vout, pin 3 = Vin. |
| U3 | **ICS-43434** (TDK, I2S MEMS mic) | _verify at order time_ | LGA-6 | Replaces INMP441 (out of stock at JLCPCB). Must be **I2S** — firmware does not support PDM. If ICS-43434 is also out of stock, substitute any in-stock I2S MEMS mic with SCK/WS/SD/VDD/GND/LR pinout. 3.3V only (5V will damage the part). |
| U4 | MAX98357A | C2682619 | TQFN-16 (3×3 mm) | I2S mono audio amp. Runs on **+5V (VBUS)** for loudest speaker volume — do NOT tie VIN to +3.3V. |
| LED1 | WS2812B-Mini | C2890037 | SMD 3535 | Addressable RGB. **No series resistor on the data line** (direct GPIO48 → DIN). Place side-firing on the perch edge. |
| J1 | USB-C receptacle (16-pin) | C165948 | HRO TYPE-C-31-M-12 | Power + USB 2.0 data. Place on the **bottom edge** of the board. |
| J2 | JST-PH 2-pin (speaker out) | C131337 | 2.0 mm pitch, vertical or right-angle | Speaker wire plugs in here. Place on a non-perch edge (top or back). |
| J3 | JST-PH 3-pin (LED eyes out) | C157929 | 2.0 mm pitch, vertical or right-angle | External LED chain for parrot eyes. Non-perch edge. |
| SW1 | **BOOT / Story button** | C221880 | PTS645 SMD tactile | GPIO0 → GND when pressed. Doubles as Story button in firmware (short press = record, hold on power-up = flash mode). |
| SW2 | **RESET button** | C221880 | PTS645 SMD tactile | EN → GND when pressed. |

**Passives (all 0805 unless noted):**

| Ref | Value | LCSC | Purpose |
|-----|-------|------|---------|
| C1 | 100 nF | C49678 | AMS1117 output decoupling (close to U2) |
| C2 | 10 µF | C15850 | AMS1117 output bulk (close to U2) |
| C3 | 100 nF | C49678 | ESP32 3V3 decoupling (close to U1) |
| C4 | 10 µF | C15850 | AMS1117 input filter (near U2 input / USB-C) |
| C5 | 10 µF | C15850 | MAX98357A VDD bulk (close to U4) |
| C6 | 100 nF | C49678 | MAX98357A VDD decoupling (close to U4) |
| C7 | 100 nF | C49678 | ICS-43434 VDD decoupling (close to U3) |
| R1 | 10 kΩ | C17414 | ESP32 EN pull-up to +3.3V |
| R2 | 5.1 kΩ | C27834 | USB-C CC1 pull-**down to GND** |
| R3 | 5.1 kΩ | C27834 | USB-C CC2 pull-**down to GND** |
| R5 | 100 kΩ | C25803 | MAX98357A SD_MODE pull-up to VDD (enables amp) |

**NOTE**: No R4. The 330 Ω LED current-limit resistor from the earlier v1 design is removed — WS2812 data line is direct GPIO48 → DIN.

---

## GPIO Pin Assignments (from working breadboard — DO NOT CHANGE)

| GPIO | Function | Connected to |
|------|----------|-------------|
| GPIO0 | BOOT / Story button | SW1 → GND |
| GPIO4 | Mic SD (I2S data) | U3 SD |
| GPIO5 | Mic WS (I2S word select) | U3 WS |
| GPIO6 | Mic SCK (I2S clock) | U3 SCK |
| GPIO10 | Amp DIN | U4 DIN |
| GPIO11 | Amp LRCLK | U4 LRCLK |
| GPIO12 | Amp BCLK | U4 BCLK |
| GPIO19 | USB D- | J1 D- |
| GPIO20 | USB D+ | J1 D+ |
| GPIO48 | RGB LED data | LED1 DIN |
| EN | Reset | R1 pull-up + SW2 → GND |

All other GPIOs left floating.

---

## Layout Rules (must match)

See `polly-board/polly_board_v2_final.png` for the visual reference — this is what the approved design looks like.

1. **Board size: 45 × 35 mm**, 2-layer.
2. **Perch edge** (the edge that faces outward through the 3D-printed stump wall) carries all user-facing components:
   - Left to right: **SW2 (Reset) — LED1 — U3 (Mic) — SW1 (Story/BOOT)**
   - **Minimum 15 mm between SW1 and SW2** (button cap clearance, ergonomic press)
   - Mic **acoustic port faces outward sideways**, not down through the PCB
   - LED side-firing through a window in the stump
   - All four components flush with or within 1 mm of the Edge.Cuts boundary
3. **Bottom edge** carries USB-C and six labeled test points: **3P3, GND, EN, TX, RX, BOOT** (for UART-based firmware recovery via pogo pins).
4. **JSTs (J2 speaker, J3 LED eyes)** on a non-perch edge — top or back. Wires route internally.
5. **Mic ↔ speaker JST** kept as far apart as the board allows, to reduce acoustic feedback.
6. **ESP32 PCB antenna** overhangs board edge OR has no ground pour / no copper directly beneath it.

---

## Non-negotiable electrical details (previous designer got these wrong — don't repeat)

- **CC1 and CC2**: 5.1 **kΩ** (NOT 5.1 Ω) pull-**down** to GND (NOT pull-up to 3.3V). USB-C host will refuse to supply power otherwise.
- **USB D+ = GPIO20, USB D- = GPIO19** (native USB). NOT GPIO38 / GPIO45.
- **SW1 (BOOT) on GPIO0**. **SW2 (RESET) on EN** (not GPIO18 — GPIO18 has no boot/reset function).
- **R1 (EN pull-up) tied to EN pin**, not some random GPIO.
- **ICS-43434 VDD = +3.3V only**. +5V damages it.
- **MAX98357A VIN = +5V (VBUS)**, NOT +3.3V (quieter at 3.3V).
- **WS2812B data line direct from GPIO48** — no series resistor.
- **ESP32 module 3V3 pin → +3.3V rail, GND pins → GND**. Not swapped. (Yes, this happened on v1.)
- **Ground pour on both layers**, connected by vias, clear of antenna area.

---

## What to deliver back

1. KiCad project (`.kicad_pro`, `.kicad_sch`, `.kicad_pcb`) committed to `hardware/polly-board/`
2. JLCPCB-ready gerbers (zip) under `hardware/polly-board/production/`
3. BOM CSV in LCSC format — columns: `Comment, Designator, Footprint, LCSC`
4. CPL / POS CSV — columns: `Designator, Mid X, Mid Y, Rotation, Layer`
5. Assembly drawing showing ICS-43434 acoustic-port orientation (recommended)

Order quantity: **5–10 prototypes first** for validation before any production run.
