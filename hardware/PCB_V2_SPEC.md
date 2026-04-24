# Polly PCB v2 — Fully Assembled Production Board

## Status
**Schematic + PCB layout finalized by Paul P. (Upwork), April 17, 2026.** Glen approved; Paul closed his contract April 20 with ~24 hours logged. A separate designer was engaged to produce the manufacturing files (gerbers, BOM, CPL) from Paul's KiCad output and has not responded as of this file's date — if they don't surface, a new designer can pick this up directly from Paul's KiCad files.

**What a new designer needs to know:**
- The **schematic and board layout are done**. The remaining work is purely producing JLCPCB-ready manufacturing outputs: gerbers, drill files, a BOM CSV in LCSC format, and a CPL/POS CSV for pick-and-place.
- Paul's final KiCad files should live in `hardware/polly-board/` — if they're missing from the repo, Glen needs to get them from Paul before handoff.
- **Do NOT trust `polly_pcb_bom_jlcpcb.csv` or `polly_pcb-top-pos.csv` currently checked in.** Those are from the earlier Fiverr revision (5-pin headers for mic/amp, "5.1" ohm pull-downs instead of 5.1 kΩ, ~10 mm button spacing instead of 15 mm). They must be regenerated from Paul's final files.

For the full upstream paper trail, see:
- `polly-board/SCHEMATIC-FIXES.md` — 20 fixes applied to the first (Fiverr) designer's schematic
- `polly-board/DESIGNER-REVIEW.md` — review of first designer's revised schematic
- `polly-board/PCB-STATUS.md` — verified net list after schematic fixes

## Goal
Board comes from JLCPCB fully assembled. Zero hand soldering. Only two plug-in connections a customer ever touches: speaker wire (JST 2-pin) and LED wire for Polly's eyes (JST 3-pin). Flash firmware via USB-C, ship. No exposed programming header, no pin headers, no loose wires.

## Overview
- **MCU**: ESP32-S3-WROOM-1-N16R8 (built-in PCB antenna, 16MB flash, 8MB PSRAM)
- **Microphone**: ICS-43434 MEMS mic, I2S (soldered directly on board) — replaces INMP441 (out of stock at JLCPCB)
- **Amplifier**: MAX98357A I2S DAC (soldered directly on board)
- **LED**: WS2812B-mini addressable RGB (soldered on board, optional JST for external eyes)
- **Power**: USB-C 5V input → AMS1117-3.3 for 3.3V rail
- **Buttons**: BOOT (GPIO0, doubles as "Story" button in firmware) + RESET (EN) — minimum 15 mm apart on the perch edge
- **Programming**: USB-C for flashing. UART fallback exposed as **test points only** (no through-hole header, no DNP connector)
- **Board size**: 36 mm × 45 mm (2-layer)

---

## Components & LCSC Part Numbers

### U1 — ESP32-S3-WROOM-1-N16R8
- **LCSC**: C2913202
- **Package**: SMD module (19.2mm x 18mm)
- **CRITICAL**: Must be N16R8 (16MB flash + 8MB octal PSRAM). **NO SUBSTITUTIONS.** Previous order substituted N4R2 which is incompatible.
- Built-in PCB antenna (NOT the 1U variant — no external antenna needed)
- Pin assignments below

### U2 — AMS1117-3.3 (3.3V Regulator)
- **LCSC**: C6186
- **Package**: SOT-223
- **Connections**: VIN → +5V (VBUS), VOUT → +3.3V rail, GND → GND

### U3 — ICS-43434 MEMS Microphone (I2S)
- **LCSC**: confirm against Paul's final BOM when received. ICS-43434 was confirmed in JLCPCB stock as of Apr 2026; if it has since gone out of stock, the replacement must be **I2S** (not PDM — firmware does not support PDM).
- **Why not INMP441**: the original spec called for INMP441 (C2837371) but it was out of stock at JLCPCB when Paul sourced components. ICS-43434 (TDK) is the same-family successor — same I2S interface, same LGA-6 footprint class, and drop-in compatible with the firmware's SCK/WS/SD pinout.
- **Package**: LGA-6 (≈4×3 mm, bottom-port MEMS)
- **Connections**:
  - SCK → GPIO6 (clock)
  - WS → GPIO5 (word select)
  - SD → GPIO4 (data out)
  - L/R (channel select) → GND (hard-wired on PCB trace — selects left channel)
  - VDD → +3.3V (do NOT connect to +5V — will damage the part)
  - GND → GND
- **PCB notes**:
  - **Edge-mounted on the perch edge** — acoustic port faces outward (sideways through the stump wall), NOT down through the PCB
  - Verify ICS-43434 port orientation against the datasheet before placing — pinout and port location can differ from INMP441
  - Keep away from noisy traces (power, high-speed digital)
  - Keep as far as practical from the speaker JST to reduce acoustic feedback
  - Recommended: 100nF decoupling cap on VDD close to the mic

### U4 — MAX98357A I2S Amplifier
- **LCSC**: C2682619 (or search "MAX98357AETE+T")
- **Package**: TQFN-16 (3mm x 3mm)
- **Connections**:
  - BCLK → GPIO12 (bit clock)
  - LRCLK → GPIO11 (left/right clock)
  - DIN → GPIO10 (data in)
  - VDD → +5V (VBUS) — amp runs on 5V for louder output
  - GND → GND
  - GAIN → leave unconnected (default 9dB) or tie to GND for 12dB
  - SD_MODE → pull high with 100kΩ to VDD (enables amp; can tie to GPIO for mute control)
  - OUTP → Speaker + (via JST connector)
  - OUTN → Speaker - (via JST connector)
- **Supporting components**:
  - C5: 10µF ceramic cap on VDD (close to chip)
  - C6: 0.1µF ceramic cap on VDD (close to chip)
  - FB1: Ferrite bead on VDD line (optional, reduces noise)
  - R5: 100kΩ pull-up on SD_MODE to VDD

### LED1 — WS2812B-Mini (Addressable RGB LED)
- **LCSC**: C2890037 (or search "WS2812B-Mini" 3.5x3.5mm)
- **Package**: SMD 3535
- **Connections**:
  - DIN → GPIO48 (data in — NO series resistor, direct connection)
  - VDD → +3.3V or +5V
  - GND → GND
  - DOUT → JST connector pin 1 (for daisy-chaining to external LED eyes)
- **PCB notes**:
  - NO resistor on data line (remove R4 from v1 design)
  - Place on board edge so it's visible, or just use as data passthrough to JST

### J1 — USB-C Receptacle (Power + Data)
- **LCSC**: C165948 (HRO TYPE-C-31-M-12, 16-pin)
- **Connections** (same as v1):
  - VBUS → +5V rail
  - GND → GND
  - CC1 → 5.1kΩ → GND (R2)
  - CC2 → 5.1kΩ → GND (R3)
  - D+ → GPIO20 (USB data)
  - D- → GPIO19 (USB data)

### J2 — Speaker Output (JST-PH 2-pin)
- **LCSC**: C131337 (JST-PH 2.0mm, right-angle or vertical)
- **Connections**:
  - Pin 1 → MAX98357A OUTP
  - Pin 2 → MAX98357A OUTN

### J3 — LED Eyes (JST-PH 3-pin)
- **LCSC**: C157929 (JST-PH 2.0mm 3-pin, right-angle or vertical)
- **Connections**:
  - Pin 1 → WS2812B DOUT (data for external LEDs)
  - Pin 2 → +5V (power for external LEDs)
  - Pin 3 → GND

### SW1 — BOOT / Story Button
- **LCSC**: C221880 (PTS645 SMD tactile) — or right-angle / side-actuated equivalent (see perch-edge notes below)
- **Connection**: GPIO0 → GND when pressed
- **Firmware dual-use**: short press triggers story recording; holding on power-up enters flash mode. There is **no separate Story button** on the board — BOOT doubles as Story.

### SW2 — RESET Button
- **LCSC**: C221880 — or right-angle / side-actuated equivalent (see perch-edge notes below)
- **Connection**: EN → GND when pressed
- **Spacing from SW1**: minimum **15 mm** on the perch edge — needed so 3D-printed button caps don't collide and a user can press one without hitting the other.

### Passive Components

| Ref | Value | Package | LCSC | Purpose |
|-----|-------|---------|------|---------|
| C1 | 100nF | 0805 | C49678 | Regulator output decoupling |
| C2 | 10µF | 0805 | C15850 | Regulator output bulk |
| C3 | 100nF | 0805 | C49678 | ESP32 decoupling |
| C4 | 10µF | 0805 | C15850 | Regulator input filter |
| C5 | 10µF | 0805 | C15850 | MAX98357A VDD bulk |
| C6 | 100nF | 0805 | C49678 | MAX98357A VDD decoupling |
| C7 | 100nF | 0805 | C49678 | INMP441 VDD decoupling |
| R1 | 10kΩ | 0805 | C17414 | EN pull-up |
| R2 | 5.1kΩ | 0805 | C27834 | USB CC1 pull-down |
| R3 | 5.1kΩ | 0805 | C27834 | USB CC2 pull-down |
| R5 | 100kΩ | 0805 | C25803 | MAX98357A SD_MODE pull-up |

**NOTE**: No R4 in v2. The 330Ω resistor on GPIO48 from v1 is removed — WS2812 needs a direct data connection.

---

## ESP32-S3 GPIO Pin Assignments

| GPIO | ESP32 Module Pin | Function | Connected To |
|------|-----------------|----------|-------------|
| GPIO0 | Pin 27 | BOOT button | SW1 → GND |
| GPIO4 | Pin 4 | Mic SD (data) | INMP441 SD |
| GPIO5 | Pin 5 | Mic WS (word select) | INMP441 WS |
| GPIO6 | Pin 6 | Mic SCK (clock) | INMP441 SCK |
| GPIO10 | Pin 18 | Amp DIN (data) | MAX98357A DIN |
| GPIO11 | Pin 19 | Amp LRC (left/right clock) | MAX98357A LRCLK |
| GPIO12 | Pin 20 | Amp BCLK (bit clock) | MAX98357A BCLK |
| GPIO19 | Pin 13 | USB D- | USB-C D- |
| GPIO20 | Pin 14 | USB D+ | USB-C D+ |
| GPIO48 | Pin 25 | LED Data | WS2812B DIN |
| EN | Pin 3 | Reset | R1 pull-up + SW2 → GND |

All other GPIO pins unused and left floating.

---

## PCB Layout Notes for Designer

### Placement
- ESP32 module near center, antenna end overhanging board edge OR clear of ground pour
- AMS1117 near USB-C connector (short power path)
- INMP441 near board edge, sound hole facing outward/upward
- MAX98357A near JST speaker connector
- Decoupling caps as close as possible to their respective ICs

### Perch Edge — Buttons, LED & Mic Cluster (IMPORTANT)
The PCB mounts **vertically** inside a 3D-printed parrot stump/perch that sits on a table. One edge of the board (the "perch edge") faces outward through the side of the stump. **All user-facing components must be grouped on this single edge.**

**Components on the perch edge** (final order, left to right, as approved with Paul):

```
SW2 (Reset) ─── LED1 ─── U3 (Mic) ─── SW1 (Story/Boot)
           ≥15 mm between SW1 and SW2 end-to-end
```

**Why the mic is on the perch edge:** The board is vertical inside the stump. If the mic faces down (bottom of board), it would be muffled against the table. If it faces up, it's buried inside the parrot body. Mounting the mic on the perch edge means the sound hole faces outward through the stump wall — clear line to the user's voice.

**Layout requirements:**
- **Button spacing: ≥15 mm between SW1 and SW2** (center-to-center). This is a firm rule — Glen confirmed it with Paul, driven by 3D-printed button-cap clearance and ergonomic press. The earlier Fiverr-era `polly_pcb-top-pos.csv` has them ~10 mm apart, which is WRONG — regenerate CPL from Paul's final layout, don't use the old file.
- **SW1 and SW2**: Use **right-angle / side-actuated tactile switches** so the press direction is horizontal (sideways off the board, toward the user through the stump wall). If right-angle variants aren't available in JLCPCB's assembly library, place top-press switches flush with the board edge so they can still be actuated through cutouts. Button caps are part of the 3D-printed stump design.
- **LED1 (WS2812B)**: Place on the board edge **side-firing** so light shines outward through the stump. The stump will have a small window/slot for the LED to glow through.
- **U3 (ICS-43434 mic)**: Mount on the perch edge with the **acoustic port hole facing outward** (not down through the PCB). Verify port orientation against the ICS-43434 datasheet before placing — do NOT copy the INMP441 orientation from memory, the port location may differ. The stump has a small hole aligned with the mic for voice pickup. Keep the mic as far as practical from the speaker JST (J2) to reduce acoustic feedback.
- **Alignment**: All four components should be flush with or within 1 mm of the Edge.Cuts boundary on the perch edge. The 3D-printed stump has precise cutouts for buttons, LED window, and mic hole — tolerances assume this alignment.
- **USB-C connector (J1)**: Place on the **bottom edge** (the edge that faces down into the table). Power cable runs out the bottom of the stump, hidden from view. USB-C is only used for flashing and power, not daily interaction.
- **JST connectors (J2 speaker, J3 LED eyes)**: Place on a non-perch edge (top or back). Wires run internally through the parrot body.
- **Mid-board programming pads**: Expose UART as **test points only** (no through-hole header, no DNP connector, no castellated pads). Glen's rule: nothing exposed to the customer except USB-C and the two JSTs. Test points give a bench-tech probe access if firmware ever needs recovery.

### Routing
- Keep analog audio traces (INMP441 SD, MAX98357A output) away from digital noise
- Ground pour on both layers
- No copper under ESP32 antenna area
- VDD and GND traces to INMP441 should be clean (no switching noise nearby)
- USB D+/D- should be ~90Ω differential impedance (short traces OK)

### Ground Pour
- Both layers, connected with vias
- Keep clear under ESP32 antenna area

### Board Size
- **Final: 36 mm × 45 mm** (reduced from the original 70×50 target once Paul saw component density on the reworked layout)
- 2-layer (F.Cu + B.Cu)

---

## What the Customer Gets

A fully assembled PCB with:
1. ESP32-S3 with WiFi (no external antenna)
2. Built-in microphone (hears voice)
3. Built-in amplifier (drives speaker)
4. RGB LED (status indicator)
5. USB-C (power + firmware flash)
6. Two JST connectors to plug in: **speaker** and **LED eyes**

Flash firmware via USB-C. Plug in speaker. Plug in LED wire to parrot eyes. Done.

---

## JLCPCB Order Notes

1. **SMT Assembly**: All components assembled by JLCPCB (both sides if needed)
2. **BOM verification**: Verify ALL LCSC part numbers before ordering. Parts go out of stock.
3. **NO SUBSTITUTIONS on U1 (ESP32-S3-WROOM-1-N16R8, C2913202)**. Add order note: "Do not substitute ESP32 module. Must be N16R8 variant."
4. **Quantity**: Order 5-10 prototypes first to verify before production run
5. **Include JST connectors in BOM** — they should solder the JST headers on the board too

---

## Files Needed from Designer

1. Updated KiCad schematic (.kicad_sch)
2. Updated PCB layout (.kicad_pcb)
3. JLCPCB-ready exports:
   - Gerber files (board outline, copper, mask, silk, drill)
   - BOM CSV (LCSC format: Comment, Designator, Footprint, LCSC Part#)
   - CPL/POS CSV (component placement: Designator, Mid X, Mid Y, Rotation, Layer)
4. Assembly drawings (if needed for INMP441 orientation)

## Existing KiCad Project

Base files in `hardware/polly-board/`:
- `polly_pcb.kicad_pro` — project
- `polly_pcb.kicad_sch` — schematic (v1/Fiverr revision — Paul's finalized schematic should replace this once delivered)
- `polly_pcb.kicad_pcb` — layout (v1/Fiverr revision — Paul's finalized layout should replace this once delivered)
- `PCB-STATUS.md` — v1 net list reference (pin assignments still valid)

---

## Designer Handoff — What's Left To Finish

If a new designer is picking this up to produce manufacturing files, here's the punch list. **The schematic and board layout are already done** (by Paul P., Apr 2026). This is not a from-scratch redesign — do not re-route the board unless Paul's final files turn out to be unrecoverable.

### 1. Obtain Paul's final KiCad files
- Glen to request from Paul, or retrieve from Upwork message attachments (last deliverable was posted Apr 16–17, 2026 with screenshot reference `image (311).png`).
- Expected files: `polly_pcb.kicad_sch`, `polly_pcb.kicad_pcb`, `polly_pcb.kicad_pro`, and any library tables Paul added.
- Drop them into `hardware/polly-board/`, replacing the v1 files currently there.

### 2. Verify Paul's design against this spec
Before generating manufacturing files, open the KiCad project and confirm:
- [ ] Mic footprint is **ICS-43434** (LGA-6), acoustic port facing outward on the perch edge
- [ ] SW1 and SW2 are **≥15 mm apart** on the perch edge
- [ ] Perch-edge order is SW2 — LED1 — U3 — SW1 (left to right)
- [ ] USB-C on the bottom edge
- [ ] J2 (speaker JST) and J3 (LED eyes JST) on a non-perch edge
- [ ] No mid-board programming header — UART exposed as test points only
- [ ] R2, R3 are **5.1 kΩ** pull-downs to GND on CC1/CC2 (NOT 5.1 ohms, NOT pull-ups — this was bug #1 from the Fiverr revision)
- [ ] ESP32 3V3 and GND are not swapped (Fiverr-revision bug #2)
- [ ] USB D+/D- on **GPIO20 / GPIO19**, not GPIO38 / GPIO45
- [ ] SW1 → GPIO0, SW2 → EN (not GPIO18)
- [ ] ICS-43434 VDD tied to **+3.3V**, not +5V
- [ ] MAX98357A VIN tied to **+5V (VBUS)**, not +3.3V
- [ ] WS2812B DIN wired directly to GPIO48 (no series resistor — R4 removed from v1 design)
- [ ] Board outline is **36 × 45 mm**

Full fix list is in `hardware/polly-board/SCHEMATIC-FIXES.md` (20 original errors) and `hardware/polly-board/DESIGNER-REVIEW.md` (remaining issues after first revision). Paul's final design should have all of these resolved — this checklist is just a spot-check.

### 3. Generate JLCPCB-ready outputs
- **Gerbers**: standard JLCPCB preset (F.Cu, B.Cu, F.Mask, B.Mask, F.Silks, B.Silks, Edge.Cuts, F.Paste, B.Paste, and drill files)
- **BOM CSV**: LCSC format — columns `Comment, Designator, Footprint, LCSC`. Every line must have a valid in-stock LCSC part number. Verify every part right before ordering; LCSC parts go out of stock routinely.
- **CPL / POS CSV**: pick-and-place. Columns: `Designator, Mid X, Mid Y, Rotation, Layer`
- Save outputs into `hardware/polly-board/production/` (create the folder). Do NOT overwrite the stale `polly_pcb_bom_jlcpcb.csv` or `polly_pcb-top-pos.csv` already in the repo — those are v1 Fiverr-era and kept for history only.

### 4. Critical order notes for JLCPCB
- **U2 (ESP32 module)**: the BOM entry must be `ESP32-S3-WROOM-1-N16R8` / **LCSC C2913202**. **Add a human-readable order note: "Do not substitute the ESP32 module. Must be N16R8 (16MB flash + 8MB octal PSRAM)."** A previous order was substituted to N4R2, which is incompatible with this firmware and bricked the batch.
- **SMT assembly**: both sides if Paul placed components on F.Cu and B.Cu (confirm from his layout)
- **Include the JST headers (J2, J3) in the SMT BOM** — they should be soldered by JLCPCB too, not hand-soldered later
- **Quantity**: order 5–10 prototypes first, validate, then scale

### 5. Deliverables back to Glen
- `.zip` of gerbers + drill
- BOM CSV
- CPL CSV
- Assembly drawing (if ICS-43434 orientation needs it — recommended)
- Updated KiCad project committed to the repo

---

## History

- **2026-03-02** — Initial schematic from Fiverr contractor; 20 errors documented in `SCHEMATIC-FIXES.md`
- **2026-03-02** — Fiverr designer's revision reviewed; 4 real fixes still needed plus 3 clarifications (see `DESIGNER-REVIEW.md`)
- **2026-03-03** — Schematic verified correct after Fiverr fixes applied (`PCB-STATUS.md`)
- **2026-04-08** — Upwork contract awarded to Paul P. for PCB layout
- **2026-04-09** — Paul flagged MSM261DGT003 as PDM (incompatible with firmware) and INMP441 as out of stock; Glen proposed ICS-43434 (TDK, I2S, LGA-6) as replacement
- **2026-04-12** — Paul confirmed ICS-43434 in stock, proposed converting mid-board programming header to test points
- **2026-04-13** — Glen confirmed: keep BOOT + RESET only (BOOT doubles as Story in firmware), 15 mm button separation, test points over header
- **2026-04-14** — Paul delivered reworked layout at **36 × 45 mm**; MEMS mic confirmed I2S; programming header converted to test points
- **2026-04-16** — Paul posted final PCB layout for review (`image (311).png` in Upwork thread)
- **2026-04-17** — Glen approved
- **2026-04-20** — Paul closed contract, ~24 hours logged. Manufacturing-file generation handed to a separate designer (currently unresponsive as of 2026-04-24).
