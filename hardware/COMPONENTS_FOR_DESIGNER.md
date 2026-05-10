# Polly PCB v2 — Canonical Spec

**Source of truth:** `hardware/polly-board/Polly_v2.*` — the KiCad project Paul P. (Upwork) delivered in April 2026.
The schematic, BOM, CPL, and gerbers there are what gets manufactured. This document explains the choices and the
non-negotiable details so a new designer can review or extend the board without re-litigating decisions.

**Board:** 45 × 35 mm, 2-layer FR4, fully SMT-assembled by JLCPCB.

**End-user connections (only these are customer-facing):**
- USB-C (power + firmware flash)
- JST-PH 2-pin SMD (speaker wire out)
- JST-PH 3-pin SMD (LED chain to Polly's eyes)

No exposed pin headers. No hand soldering. UART fallback exposed as **labeled SMD test pads along the bottom edge**
(pogo-pin probe, not a connector).

---

## BOM (Paul's v2, manufactured by JLCPCB)

All part numbers are JLCPCB LCSC codes. Verify stock right before ordering — LCSC parts rotate in and out.

| Ref | Component | LCSC | Package | Notes |
|-----|-----------|------|---------|-------|
| U1 | **ESP32-S3-WROOM-1-N16R8** | **C2913202** | SMD module | **DO NOT SUBSTITUTE.** Must be N16R8 (16 MB flash, 8 MB octal PSRAM). A previous order was substituted to N4R2, which is incompatible with the firmware. Add this as a human-readable order note to JLCPCB. |
| U2 | MAX98357AETE+T | C910544 | TQFN-16 (3×3 mm) | I2S mono audio amp. Runs on **+5V (SP_5V)** for max volume — do NOT tie VDD to +3.3V. **GAIN_SLOT tied to GND = 15 dB (loudest setting).** **SD_MODE controlled by GPIO13** (firmware drives high to enable amp, low to mute — saves power and kills idle hiss). |
| U3 | AP7361-33FGE-7 | C460392 | DFN-8 | 5V → 3.3V LDO regulator, 1 A capability, low noise. Replaces AMS1117 from the v1 spec — better part for clean audio rails. |
| U6 | **ICS-43434** (TDK, I2S MEMS mic) | **C5656610** | LGA-6 | I2S MEMS mic. Replaces MSM261DGT003 (PDM, incompatible with firmware) and INMP441 (out of stock at JLCPCB). 3.3V only (5V will damage the part). |
| LED1 | **SK6812SIDE-A-RVS** | **C2890037** | SMD 4P, side-emit reverse-mount | Addressable RGB, side-firing through a window in the perch / stump wall. Same one-wire 800 kHz protocol as WS2812 — firmware works unchanged. **No series resistor on the data line** (direct GPIO48 → DIN). DOUT chains off-board through the LED-eyes JST. |
| USBC1 | USB-C receptacle (16-pin) | C165948 | TYPE-C-31-M-12 | Power + USB 2.0 data. Place on the **bottom edge** of the board. |
| CN1 | JST-PH 2-pin SMD (speaker out) | **C295747** | S2B-PH-SM4-TB, 2.0 mm pitch, side-entry SMD | Pin 1 = OUTP, Pin 2 = OUTN. SMD = no through-hole soldering at JLCPCB. |
| U4 | JST-PH 3-pin SMD (LED eyes out) | **C265101** | S3B-PH-SM4-TB, 2.0 mm pitch, side-entry SMD | **Pin 1 = DATA (chain-out from LED1 DOUT), Pin 2 = +5V, Pin 3 = GND.** Customer pigtails MUST match this pin order — DATA is on pin 1, not the middle pin. |
| KEY1 | **RESET button** | C255810 | SMD tactile (1TS003B-2500-3500A-CT) | EN → GND when pressed. |
| KEY2 | **BOOT / Story button** | C255810 | SMD tactile (1TS003B-2500-3500A-CT) | GPIO0 → GND when pressed. Doubles as Story button in firmware (short press = record, hold on power-up = flash mode). |

**Passives (all 0603):**

| Ref | Value | LCSC | Purpose |
|-----|-------|------|---------|
| C1, C20 | 4.7 µF | C69335 | USB_5V / SP_5V bulk |
| C10, C12, C13, C18, C2, C21, C3, C4, C5 | 100 nF | C1590 | Decoupling across rails (ESP32, LDO, amp, mic) — including **C2 100nF on EN-to-GND** (RC reset filter) and **C3 100nF on BOOT-to-GND** (debounce) |
| C11, C17, C19, C6, C7, C8, C9 | 10 µF | C70225 | Bulk caps on 3.3V rails and USB VBUS |
| C14, C15 | 470 pF | C1620 | Class-D speaker output EMI filter (paired with L2/L3) |
| C16 | 1 µF | C1592 | LED chain bulk |
| L1, L2, L3, L4 | 120 Ω @ 100 MHz | C14709 | Ferrite beads — **L1 splits USB_5V from SP_5V** (audio gets clean 5V), **L2/L3 on speaker outputs** (Class-D filter), **L4 splits ESP_3V3 from MIC_3V3** (clean mic supply) |
| R1 | 100 kΩ | C14675 | MAX98357A SD_MODE pull-up to GPIO13 |
| R2, R3 | 5.1 kΩ | C14677 | USB-C CC1 / CC2 pull-**downs to GND** |
| R4, R5 | 10 kΩ | C15401 | EN pull-up + BOOT pull-up to +3.3V |

---

## GPIO Pin Assignments (firmware-locked — DO NOT CHANGE)

| GPIO | Function | Connected to |
|------|----------|-------------|
| GPIO0 | BOOT / Story button | KEY2 → GND |
| GPIO4 | Mic SD (I2S data) | U6 SD |
| GPIO5 | Mic WS (I2S word select) | U6 WS |
| GPIO6 | Mic SCK (I2S clock) | U6 SCK |
| GPIO10 | Amp DIN | U2 DIN |
| GPIO11 | Amp LRCLK | U2 LRCLK |
| GPIO12 | Amp BCLK | U2 BCLK |
| **GPIO13** | **Amp SD_MODE (software enable)** | U2 SD_MODE via R1 100k. Firmware must drive HIGH at boot to enable the amp. |
| GPIO19 | USB D- | USBC1 D- |
| GPIO20 | USB D+ | USBC1 D+ |
| GPIO48 | RGB LED data | LED1 DIN |
| EN | Reset | R4 pull-up + KEY1 → GND, with C2 100nF RC filter |

All other GPIOs left floating.

---

## Layout Rules (must match)

See `polly-board/polly_board_v2_final.png` for the visual reference.

1. **Board size: 45 × 35 mm**, 2-layer.
2. **Perch edge** (the edge that faces outward through the 3D-printed stump wall) carries all user-facing components:
   - Left to right: **KEY1 (Reset) — LED1 — U6 (Mic) — KEY2 (Story/BOOT)**
   - **Minimum 15 mm between KEY1 and KEY2** (button cap clearance, ergonomic press)
   - Mic acoustic port faces outward sideways, not down through the PCB
   - LED side-firing through a window in the stump
   - All four components flush with or within 1 mm of the Edge.Cuts boundary
3. **Bottom edge** carries USB-C and six labeled SMD test pads: **3P3, GND, EN, TX, RX, BOOT** (for UART-based firmware recovery via pogo pins).
4. **JSTs (CN1 speaker, U4 LED eyes)** on a non-perch edge — top or back. Wires route internally.
5. **Mic ↔ speaker JST** kept as far apart as the board allows, to reduce acoustic feedback.
6. **ESP32 PCB antenna** overhangs board edge OR has no ground pour / no copper directly beneath it.

---

## Non-negotiable electrical details (don't repeat past mistakes)

- **CC1 and CC2**: 5.1 **kΩ** (NOT 5.1 Ω) pull-**down** to GND (NOT pull-up to 3.3V). USB-C host will refuse to supply power otherwise.
- **USB D+ = GPIO20, USB D- = GPIO19** (native USB).
- **KEY1 (RESET) on EN**, **KEY2 (BOOT) on GPIO0**.
- **R4 (EN pull-up) tied to EN pin** + **C2 100nF on EN-to-GND** for clean reset.
- **ICS-43434 VDD = +3.3V only**. +5V damages it.
- **MAX98357A VDD = +5V (SP_5V via L1 ferrite bead from VBUS)**, NOT +3.3V (quieter at 3.3V).
- **MAX98357A GAIN_SLOT = GND** for 15 dB max gain.
- **MAX98357A SD_MODE = GPIO13 via R1 100k** — firmware must drive HIGH at boot.
- **WS2812 / SK6812 data line direct from GPIO48** — no series resistor.
- **ESP32 module 3V3 pin → +ESP_3P3, GND pins → GND**. Not swapped.
- **Ground pour on both layers**, connected by vias, clear of antenna area.

---

## What to deliver

1. KiCad project (`.kicad_pro`, `.kicad_sch`, `.kicad_pcb`) — already committed at `hardware/polly-board/Polly_v2.*`
2. JLCPCB-ready gerbers (zip) — already at `hardware/polly-board/production/Polly_V2.zip`
3. BOM CSV in LCSC format (`Designator, Footprint, Quantity, Value, LCSC Part #`) — at `hardware/polly-board/production/Polly_V2_bom.csv`
4. CPL / POS CSV (`Designator, Mid X, Mid Y, Rotation, Layer`) — at `hardware/polly-board/production/Polly_V2_positions.csv`

Order quantity: **5–10 prototypes first** for validation before any production run.

---

## Alternate designs in flight

- **Paul P. (Upwork) — `hardware/polly-board/`** — current canonical, manufactured-ready.
- **Fiverr designer (alt) — `hardware/polly-board-alt-fiverr/`** — alternate v2 layout being developed in parallel as a price/quality comparison. Glen plans to assemble both and bench-test before locking in a single design for production.

If you're a new designer joining the project, **start from Paul's files**. If asked to do an "alt" version, copy his project as your starting reference rather than redrawing from scratch.
