# Designer's Revised Schematic — Review Notes

**Date:** 2026-03-02
**Reviewed against:** Working breadboard prototype + SCHEMATIC-FIXES.md

---

## What the Designer FIXED CORRECTLY

| Item | Before | After | Status |
|------|--------|-------|--------|
| ESP32 3V3/GND | Swapped (would fry chip) | 3V3 → +3.3V, GND → GND | FIXED |
| VBUS → Regulator | SBU2 was feeding U1 | VBUS → U1 pin 3 (IN) | FIXED |
| U1 GND | Floating | Connected to GND | FIXED |
| USB-C GND | Isolated | Connected to GND | FIXED |
| USB D+ | GPIO38 (wrong) | GPIO20 (correct) | FIXED |
| USB D- | GPIO45 (wrong) | GPIO19 (correct) | FIXED |
| Shield | Floating | Connected to GND | FIXED |
| EN pull-up (R1) | Connected to GPIO37 | Connected to EN | FIXED |
| R3/R5 CC values | 5.1 ohm | 5.1kΩ | FIXED |
| GPIO48 LED | Was on GPIO43 | Now on J4 through R4 (330Ω) | FIXED |
| C4 | On wrong net | Between VBUS/IN and GND | FIXED |

---

## ISSUES STILL REMAINING

### Issue 1: CC1 and CC2 are PULL-UPS — should be PULL-DOWNS (CRITICAL)

**What the designer did:**
- CC1 → R3 (5.1kΩ) → **+3.3V**
- CC2 → R5 (5.1kΩ) → **+3.3V**

**What it should be:**
- CC1 → R3 (5.1kΩ) → **GND**
- CC2 → R5 (5.1kΩ) → **GND**

**Why this matters:** The USB-C spec requires 5.1kΩ pull-DOWN resistors to GND on CC1 and CC2. This tells the USB host "I am a device that wants power" (UFP / sink). Pull-ups to 3.3V would signal the opposite — that this board is a power SOURCE (DFP / host). The USB host may refuse to supply power, or worse, both sides try to source power.

**Fix:** Change R3 and R5 from connecting to +3.3V to connecting to **GND**.

---

### Issue 2: SW2 connects to GPIO18 — should be EN for reset

**What the designer did:**
- SW1 → GPIO0 → GND (labeled "Reset")
- SW2 → GPIO18 → GND

**What it should be:**
- SW1 → GPIO0 → GND (this is the **BOOT** button, not reset)
- SW2 → **EN** → GND (this is the **RESET** button)

**Why this matters:** There is no reset button on this board. SW2 on GPIO18 does nothing useful — GPIO18 has no special boot/reset function. The EN pin already has R1 (10kΩ) pulling it high, so it just needs a button to pull it low for reset.

To flash firmware, you hold BOOT (GPIO0 low), tap RESET (EN low), then release both. Without a working reset button, the user has to unplug/replug USB to reset.

**Fix:**
- Disconnect SW2 from GPIO18
- Connect SW2 between **EN** and **GND**
- Relabel SW1 as "BOOT" (not "Reset")
- Relabel SW2 as "RESET"

---

### Issue 3: J2 Pin 1 = +5V — INMP441 mic is a 3.3V device

**What the designer did:** J2 (mic header) Pin 1 → +5V

**What it should be:** The INMP441 mic is rated **1.8V to 3.3V max**. Applying 5V will damage it.

**Fix:** J2 power pin → **+3.3V** rail (AMS1117 output), not +5V

---

### Issue 4: J5 only has 4 pins — needs 5 pins

**What the designer did:** J5 is a 1x4 header (message was cut off at "Pin 1 → +3.")

**What it should be:** The MAX98357A breakout board has 5 connections: BCLK, LRC, DIN, VIN, GND. A 4-pin header is missing one signal.

J5 should be **1x5** with:

| Pin | Signal | Net |
|-----|--------|-----|
| 1 | BCLK | GPIO12 |
| 2 | LRC | GPIO11 |
| 3 | DIN | GPIO10 |
| 4 | VIN | +5V (VBUS, for max speaker volume) |
| 5 | GND | GND |

**Also:** If J5 Pin 1 goes to +3.3V as the cutoff text suggests, the MAX98357A will work but at lower volume. **+5V is recommended** for audible speech volume in a room.

---

### Issue 5: J2 has 6 pins — expected 5 for INMP441

**What the designer did:** J2 is a 1x6 header. Pins 3-6 go to GPIOs (unspecified which ones).

**What it should be:** The INMP441 breakout has 5 pins: SCK, WS, SD, VDD, GND. A 6-pin header has one extra pin.

Confirm J2 pinout matches:

| Pin | Signal | Net |
|-----|--------|-----|
| 1 | SCK | GPIO6 |
| 2 | WS | GPIO5 |
| 3 | SD | GPIO4 |
| 4 | VDD | +3.3V |
| 5 | GND | GND |
| 6 | (L/R select — optional) | GND or +3.3V (sets left/right channel) |

Pin 6 could be the INMP441 L/R pin — tie to GND for left channel (default). If the designer intended this, it's fine. Just needs to be confirmed.

---

### Issue 6: R2 (10kΩ) — unclear purpose

**What the designer added:** A new R2 = 10kΩ that wasn't in the original design. Its connections aren't described.

**Possible uses:**
- Pull-up on GPIO0 (boot button) — acceptable but not required since the ESP32-S3 has an internal pull-up on GPIO0
- Something else — needs confirmation from designer

**Ask the designer:** What does R2 (10kΩ) connect between?

---

### Issue 7: AMS1117 pin numbering — verify against footprint

**What the designer described:**
- Pin 3 = IN
- Pin 2 = GND
- Pin 1 = OUT

**Standard KiCad AMS1117 symbol:**
- Pin 1 = GND
- Pin 2 = Vout (output)
- Pin 3 = Vin (input)

The designer's description has pins 1 and 2 swapped compared to the standard symbol. This might just be ChatGPT misreading the schematic, OR the designer used a different symbol/footprint with non-standard pin numbering.

**Ask the designer:** Confirm the AMS1117 symbol pin mapping matches the SOT-223 footprint. On the physical SOT-223 package: Pin 1 (left) = GND, Pin 2 (center/tab) = Vout, Pin 3 (right) = Vin.

---

## Summary

| # | Issue | Severity | Fix |
|---|-------|----------|-----|
| 1 | CC1/CC2 pull-ups instead of pull-downs | **CRITICAL** — USB won't supply power | R3, R5 → GND not +3.3V |
| 2 | SW2 on GPIO18 instead of EN | **HIGH** — no reset button | SW2 → EN pin |
| 3 | J2 power pin = +5V | **HIGH** — will damage INMP441 mic | J2 power → +3.3V |
| 4 | J5 only 4 pins | **MEDIUM** — missing a connection | Change to 1x5 header |
| 5 | J2 has 6 pins | **LOW** — verify pinout | Confirm pin 6 purpose |
| 6 | R2 (10kΩ) unknown | **LOW** — verify | Ask designer what it connects to |
| 7 | AMS1117 pin numbering | **LOW** — may be description error | Verify against footprint |

**4 of the 7 are real fixes. The other 3 are just clarifications to confirm with the designer.**
