// =============================================================================
//  MechLung.ino — Arduino UNO R4 WiFi
//  Full sensor suite (SFM3000 flow + 7x SDP811 pressure, from MechLung_Final)
//  driven through the actuator architecture from FlowTestingPY:
//  register-bounded DAC writes, position-feedback telemetry, demo sine, expanded
//  serial command set, and the more robust SFM3000 handling. Travel safety
//  itself is not this sketch's job — see the note above writeActuatorDac().
//
//  This is a merge of two sketches, not a straight copy of either:
//    - MechLung_Final.ino     — full 2-bus sensor suite, clinical presets
//    - FlowTestingPY.ino      — position feedback, demo sine, expanded commands,
//                                SFM3000 hardening
//
//  MERGE DECISIONS WORTH KNOWING ABOUT
//  ─────────────────────────────────────────────────────────────────────────
//  - Sensor reads (flow AND all 7 pressures) run in their own SENSOR_CYCLE_US
//    gate, separate from the actuator's tick-gated block — same structure as
//    MechLung_Final. FlowTestingPY read its single fast SFM3000 transaction
//    inside the tick-gated block; that does NOT scale to the 7-sensor mux
//    array, which needs many I2C transactions per scan. Before R8, a blocking
//    channel reinit alone could take ~26ms; runtime recovery is now spread
//    across loop passes for the same reason (see R8). Although the sensor
//    cycle and the actuator tick share a 10ms period (R15), they are gated
//    independently.
//  - The CSV "DATA" row only prints while a run is active (current_preset
//    != -1, i.e. a clinical preset OR demo sine) — same "don't log idle"
//    gate MechLung_Final used, extended to also cover demo sine.
//  - i2cBusRecovery() (boot-time stuck-bus clear) is kept on the main bus.
//    Both buses also use an explicit 5ms per-transaction timeout. The old
//    Renesas timeout-loop bug (arduino/ArduinoCore-renesas#66) is fixed in
//    the current core; bounding each transaction keeps a bus fault from
//    indefinitely holding the single actuator/sensor loop.
//  - No "wait for Python logger" handshake in setup() (MechLung_Final had
//    one). FlowTestingPY's whole ordering philosophy is "never let setup()
//    block on an external party" — keeping a blocking handshake here would
//    work against that.
//
//  REVISION NOTES (this version)
//  ─────────────────────────────────────────────────────────────────────────
//  R1. DATA rows are emitted on a FIXED LOG_RATE_HZ cadence instead of once
//      per loop() pass. Previously the log interval was "however long the
//      last loop happened to take", which is neither constant nor known —
//      that irregular spacing quietly corrupts anything computed against
//      time downstream (peak timing, dP/dt, resampling, spectra), and at
//      full loop speed it also generated rows faster than the link could
//      drain them. The current wire format is documented in printBanner().
//  R2. The sensor cycle is paced by SENSOR_CYCLE_US rather than free-running
//      flat out. Hammering the mux as fast as loop() allows re-reads the
//      SDP811s far faster than they update, and starves the actuator tick of
//      loop passes for no benefit.
//  R3. REMOVED — position feedback is telemetry only. The former slow bias
//      trim changed the commanded waveform based on A1 feedback; command and
//      measured position are now logged independently without feedback
//      modifying the DAC output.
//  R4. REMOVED — the SAFE_FEEDBACK-derived software travel clamp, and the
//      boot-time check that warned when a preset's peak command would clip
//      against it. That clamp was sized around an earlier, shorter prototype
//      chamber and had not been revisited since, so it silently narrowed the
//      piston's usable range for every geometry that came after it. It was
//      also duplicated work: the Jrk G2's own Input scaling, set in the Jrk
//      Configuration Utility, maps whatever voltage the Arduino's DAC puts
//      out onto the actuator's real safe travel — so the DAC value the
//      firmware writes is always confined by the Jrk regardless of what the
//      firmware itself thinks the limits are. A second, independent,
//      possibly-stale copy of that limit in firmware doesn't add safety; it
//      only adds a second place for the two numbers to disagree, and this
//      was that disagreement. The one bound still enforced in firmware is
//      writeActuatorDac()'s constrain to [0, 4095] — the 12-bit DAC
//      register's addressable range, not a travel limit — see the note
//      above that function.
//  R5. SFM3000 gets the same consecutive-failure re-init the SDP811 array
//      already had, so a transient main-bus glitch doesn't kill flow data
//      for the rest of the session.
//  R6. New commands: 'm' toggles the human-readable Monitor block (so it can
//      be silenced during a logged run), '?' reprints the banner.
//  R7. Printed precision trimmed to what the sensors actually resolve
//      (SFM3000 ~0.007 slm, SDP811 ~0.017 Pa), cutting row length by ~20%.
//  R8. Runtime sensor recovery is non-blocking. Pressure-channel recovery is
//      spread across loop passes, and SFM3000's 100ms conversion wait is now
//      a timed state rather than delay(100), so recovery cannot deliberately
//      suspend the 100Hz actuator tick.
//  R9. SFM3000 boot/recovery failures retry once per second instead of
//      permanently disabling flow reads after the first failed init.
//  R10. The Python logger sends an internal '!' heartbeat. A run started
//       while those heartbeats are present returns to centre if they stop;
//       runs started from a plain Serial Monitor remain autonomous.
//  R11. Wire and Wire1 transactions are explicitly bounded to 5ms. This
//       replaces reliance on the core's much longer default timeout.
//  R12. Clinical profiles use raised-cosine position ramps, giving zero
//       velocity at both ends of each stroke without changing peak flow.
//  R13. DATA logging runs at 100Hz over the UNO R4 WiFi native USB CDC link
//       and includes DAC command counts plus A1-derived feedback counts.
//       This rate is not intended for a 115200-baud hardware UART.
//  R14. 'c'/'C' (alias for hold) removed — H/h/0 already do this.
//  R15. Each 100Hz DATA row now carries the commanded instantaneous/peak
//       flow, breath phase, and per-sensor sample ages. Sensor acquisition is
//       phase-aligned one-for-one with DATA rows so peak-pressure records can
//       be checked for freshness and inter-channel timing skew.
//  R16. DATA cadence resynchronization is exact at the missed-deadline
//       boundary. The log deadline advances by one interval (phase-locked);
//       if the row is then still a full interval or more overdue, the
//       deadline resynchronizes to "now" and the backlog is skipped instead
//       of being replayed as a burst of rows from one sensor scan.
//  R17. actuator_clamped is sticky for one MOTION SESSION, which begins in
//       either startPreset() or startDemoSine(). Both starters clear it, so
//       a rail hit during one session never appears in the next session's
//       DATA rows.
//
//  Two buses:
//    Wire   (main bus)  — SFM3000 flow sensor only
//    Wire1  (Qwiic bus) — 7 x SDP811 via PCA9548 mux, channels 0-6 (ch 7 unused)
//                          Naming: mux channel N -> "Psens(N+1)"
//
//  SERIAL OUTPUT — two audiences on one serial link (native USB CDC):
//    - "DATA,..." CSV line at LOG_RATE_HZ, only while a run is active —
//      for the companion logging/plotting script.
//    - A throttled, human-readable Monitor block for the Serial Monitor.
//
//  SERIAL COMMANDS (all single-byte, no newline needed)
//  ─────────────────────────────────────────────────────────────────────────
//  1-4        clinical preset — sets breath rate/amplitude and starts a new
//             motion session: resets seq, the clamp flag and the feedback
//             filter, then starts logging.
//  s, S       demo sine — full-range motion demo, not physiologically
//             meaningful. Also starts a new motion session (same resets).
//  H, h, 0    hold at DAC_CENTRE / go idle. Logging stops.
//  X, x       hold at CALIBRATION_TARGET_JRK_SCALE — a second, fixed point
//             distinct from centre, used for pot calibration.
//  m, M       toggle the Monitor block on/off.
//  ?          reprint the banner / command help.
//  !          logger heartbeat (internal; arms the host watchdog).
// =============================================================================

#include <Wire.h>

// VERIFY: Confirm pins 27/26 against the installed Renesas core before relying on these fallbacks; if that core exposes the pins as non-macro identifiers, these macros can silently shadow its real values.
#ifndef WIRE1_SDA_PIN
#define WIRE1_SDA_PIN 27
#endif
#ifndef WIRE1_SCL_PIN
#define WIRE1_SCL_PIN 26
#endif

// =============================================================================
//  ACTUATOR CALIBRATION
// =============================================================================
//  Travel safety is NOT enforced here. It lives entirely in the Jrk G2's own
//  Input scaling, configured through the Jrk Configuration Utility, which
//  maps whatever voltage the Arduino's DAC outputs onto the actuator's real
//  safe travel before the Jrk's PID ever acts on it. Firmware writing a
//  value outside that mapping doesn't move the piston outside it — the Jrk
//  confines it regardless. A previous version of this sketch also enforced
//  a second, independent software clamp here (SAFE_FEEDBACK_MIN/MAX); it was
//  sized around an earlier, shorter prototype chamber, was never revisited
//  for later geometries, and duplicated a limit the Jrk already owns — see
//  revision note R4 near the top of this file. It has been removed.
//
//  DAC_CENTRE below is therefore a plain calibration constant, not derived
//  from any safety range: it is the Jrk feedback-scale value corresponding
//  to the actuator's physical centre-of-stroke position, found the same way
//  as any other calibration point (H hold, read back the Jrk's scaled
//  feedback, adjust). Re-confirm it against the Jrk's currently configured
//  Input scaling before relying on it — it was last set while that scaling
//  still assumed the removed safety window, and Input scaling changes made
//  independently of this sketch won't be reflected here automatically.
// VERIFY: DAC_CENTRE is inherited and unverified on this rig; re-derive it with the H/X hold pair before treating feedback_dac, fdbk_pct, or following error as quantitative.
static const int   DAC_CENTRE         = 1450;
static const float ACTUATOR_STROKE_MM = 300.0f;

//  DAC_HALF_RANGE is the actuator scale factor: DAC counts corresponding to
//  half the full mechanical stroke (ACTUATOR_STROKE_MM / 2). Everything that
//  converts between millimetres and DAC counts — mmToDacCounts(), and the
//  cmd_pct / fdbk_pct columns in the log — goes through it. It is a property
//  of the actuator + Jrk scaling only, independent of the Input-scaling
//  window configured in the Jrk Utility: cmd_pct/fdbk_pct report position as
//  a percentage of the actuator's full mechanical stroke, not of whatever
//  the Jrk is currently configured to permit.
// VERIFY: DAC_HALF_RANGE is used for both mm-to-command conversion and corrected-DAC/A1 percentage normalization, which may be incompatible scales and can shift tidal volume and peak flow by about 2.4%. Command a known DAC delta, measure piston travel with calipers, and determine which scale 1526 represents before correcting either use.
static const int   DAC_HALF_RANGE     = 1526;

static const float CYLINDER_DIAMETER_MM = 115.0f;
static const float V_TIDAL_ML           = 700.0f;

static const float IE_EXP_PARTS  = 2.0f;
static const float IE_INSP_PARTS = 1.0f;

static const float DAC_CORR_OFFSET = 49.0f;
static const float DAC_CORR_GAIN   = 4002.0f;

static int corrected_centre_dac = 0;

static int applyDacCorrection(int jrk_desired) {
  float dac = ((float)jrk_desired - DAC_CORR_OFFSET) * 4095.0f / DAC_CORR_GAIN;
  return constrain((int)(dac + 0.5f), 0, 4095);
}

// =============================================================================
//  OUTPUT TIMING
// =============================================================================
//  LOG_RATE_HZ is the DATA row cadence. It is deliberately decoupled from
//  both the actuator tick and the sensor cycle:
//    - it must not be faster than SENSOR_CYCLE_US, or rows repeat readings;
//    - it must be slow enough that the row bytes drain comfortably. At 100Hz
//      the expanded row is at most roughly 22-23kB/s, comfortable on the
//      UNO R4 WiFi's native USB CDC Serial link but exceeds a 115200-baud
//      hardware UART's sustainable payload.
static const uint32_t LOG_RATE_HZ   = 100;
static const uint32_t LOG_INTERVAL_US = 1000000UL / LOG_RATE_HZ;

//  One sensor scan is phase-aligned with each 100Hz DATA row. Reading faster
//  than rows are recorded only adds mux/I2C load; both sensor families update
//  much faster than 10ms in continuous mode. Per-channel ages in each row
//  make the remaining sequential mux skew explicit instead of hiding it.
static const uint32_t SENSOR_CYCLE_US = LOG_INTERVAL_US;
static const uint32_t I2C_TRANSACTION_TIMEOUT_US = 5000UL;

// =============================================================================
//  I2C BUS RECOVERY — main bus (Wire) only. The SFM3000 can be left
//  mid-transfer holding SDA low across a sketch re-upload; this clears
//  that before Wire.begin(). Must run before Wire.begin().
// =============================================================================

static void i2cBusRecovery() {
  pinMode(SDA, INPUT_PULLUP);
  pinMode(SCL, OUTPUT);

  for (int i = 0; i < 9 && digitalRead(SDA) == LOW; i++) {
    digitalWrite(SCL, LOW);
    delayMicroseconds(5);
    digitalWrite(SCL, HIGH);
    delayMicroseconds(5);
  }

  pinMode(SDA, OUTPUT);
  digitalWrite(SDA, LOW);
  delayMicroseconds(5);
  digitalWrite(SCL, HIGH);
  delayMicroseconds(5);
  digitalWrite(SDA, HIGH);
  delayMicroseconds(5);

  pinMode(SDA, INPUT);
  pinMode(SCL, INPUT);
}

// =============================================================================
//  I2C BUS RECOVERY — Wire1 (Qwiic/mux bus). Same clock-out-a-stuck-SDA
//  technique as i2cBusRecovery() above, but for WIRE1_SDA_PIN/WIRE1_SCL_PIN
//  (pins 27/26 on the R4 WiFi). Added because the main bus already had a
//  recovery path and Wire1 didn't — if a sensor or the mux is left mid-
//  transaction across a reset, SDA1 can stay held low and Wire1.begin()
//  alone won't clear it (it only configures the peripheral, it doesn't
//  clock anything out). This runs before Wire1.begin(), same as the main
//  bus's recovery does, so it doesn't touch the FSP I2C driver at all. It is
//  therefore independent of the explicit 5ms transaction timeout that setup()
//  applies afterwards (R11): the old Renesas timeout bug referenced in the
//  header was in the driver's runtime timeout handling, not in bit-banging
//  the pins before begin().
// =============================================================================

static void i2cBusRecovery1() {
  pinMode(WIRE1_SDA_PIN, INPUT_PULLUP);
  pinMode(WIRE1_SCL_PIN, OUTPUT);

  for (int i = 0; i < 9 && digitalRead(WIRE1_SDA_PIN) == LOW; i++) {
    digitalWrite(WIRE1_SCL_PIN, LOW);
    delayMicroseconds(5);
    digitalWrite(WIRE1_SCL_PIN, HIGH);
    delayMicroseconds(5);
  }

  pinMode(WIRE1_SDA_PIN, OUTPUT);
  digitalWrite(WIRE1_SDA_PIN, LOW);
  delayMicroseconds(5);
  digitalWrite(WIRE1_SCL_PIN, HIGH);
  delayMicroseconds(5);
  digitalWrite(WIRE1_SDA_PIN, HIGH);
  delayMicroseconds(5);

  pinMode(WIRE1_SDA_PIN, INPUT);
  pinMode(WIRE1_SCL_PIN, INPUT);
}

// =============================================================================
//  SFM3000 FLOW SENSOR — I2C (Wire, main bus)
// =============================================================================
//  Sensirion SFM3000, addr 0x40. flow[slm] = (raw - OFFSET) / SCALE.
//  Protocol: issue "start continuous measurement" (0x1000) once at init,
//  then just repeatedly read back the 2-byte flow word. Per the datasheet,
//  the very first measurement right after chip init is invalid and must be
//  discarded — done once here in sfm3000Init().
//
//  On a failed read, flow_slm holds its last-good value (flow_sensor_ok
//  reports which happened) so a single dropped I2C transaction doesn't put
//  a spike/dropout in the trace. Past SFM_FAIL_REINIT_THRESHOLD consecutive
//  failures the sensor is re-initialised (R5), mirroring what the SDP811
//  array already did — without it, one transient main-bus glitch left the
//  flow channel dead for the rest of the session.
// =============================================================================

static const uint8_t SFM3000_I2C_ADDR       = 0x40;
static const float   SFM3000_OFFSET_FLOW    = 32000.0f;
static const float   SFM3000_SCALE_FLOW_AIR = 140.0f;   // air/N2; 142.8 for O2

static const int SFM_FAIL_REINIT_THRESHOLD = 10;  // ~100ms at SENSOR_CYCLE_US

static bool  sfm_ok          = false; // did sfm3000Init() succeed at boot
static bool  flow_sensor_ok  = false; // did the most recent read succeed
static float flow_slm        = 0.0f;  // last valid reading; holds last-good on failure
static uint32_t flow_sample_us = 0;   // completion time of latest valid read

static uint16_t sfm_consecutive_fails = 0;
static uint32_t sfm_reinit_count      = 0;  // surfaced in the Monitor block

enum SfmRecoveryState : uint8_t {
  SFM_RECOVERY_RETRY_WAIT,
  SFM_RECOVERY_DISCARD_WAIT,
};

static const uint32_t SFM_RETRY_INTERVAL_US = 1000000UL;
static SfmRecoveryState sfm_recovery_state  = SFM_RECOVERY_RETRY_WAIT;
static uint32_t sfm_recovery_due_us         = 0;

static bool sfm3000Init();
static bool sfm3000ReadRaw(uint16_t &raw_out);
static bool sfm3000ReadFlow();

static bool timeReachedUs(uint32_t now_us, uint32_t due_us) {
  return (int32_t)(now_us - due_us) >= 0;
}

// Start continuous conversion without waiting for the first sample. Runtime
// recovery uses this split phase so the actuator loop keeps running during
// the sensor's mandatory 100ms conversion delay.
static void sfm3000BeginRecovery(uint32_t now_us) {
  sfm_ok = false;
  flow_sensor_ok = false;

  Wire.beginTransmission(SFM3000_I2C_ADDR);
  Wire.write(0x10);
  Wire.write(0x00);
  if (Wire.endTransmission() == 0) {
    sfm_recovery_state = SFM_RECOVERY_DISCARD_WAIT;
    sfm_recovery_due_us = now_us + 100000UL;
  } else {
    sfm_recovery_state = SFM_RECOVERY_RETRY_WAIT;
    sfm_recovery_due_us = now_us + SFM_RETRY_INTERVAL_US;
  }
}

static void sfm3000Service(uint32_t now_us) {
  if (sfm_ok) {
    sfm3000ReadFlow();
    return;
  }
  if (!timeReachedUs(now_us, sfm_recovery_due_us)) return;

  if (sfm_recovery_state == SFM_RECOVERY_DISCARD_WAIT) {
    uint16_t discard;
    if (sfm3000ReadRaw(discard)) {
      sfm_ok = true;
      sfm_consecutive_fails = 0;
      return;
    }
    sfm_recovery_state = SFM_RECOVERY_RETRY_WAIT;
    sfm_recovery_due_us = now_us + SFM_RETRY_INTERVAL_US;
    return;
  }

  sfm_reinit_count++;
  sfm3000BeginRecovery(now_us);
}

static bool sfm3000ReadRaw(uint16_t &raw_out) {
  if (Wire.requestFrom((int)SFM3000_I2C_ADDR, 2) != 2) return false;
  if (Wire.available() < 2) return false;
  const uint8_t hi = Wire.read();
  const uint8_t lo = Wire.read();
  raw_out = ((uint16_t)hi << 8) | lo;
  return true;
}

static bool sfm3000ReadFlow() {
  uint16_t raw;
  flow_sensor_ok = sfm3000ReadRaw(raw);

  if (flow_sensor_ok) {
    flow_slm = ((float)raw - SFM3000_OFFSET_FLOW) / SFM3000_SCALE_FLOW_AIR;
    flow_sample_us = micros();
    sfm_consecutive_fails = 0;
    return true;
  }

  if (++sfm_consecutive_fails >= SFM_FAIL_REINIT_THRESHOLD) {
    sfm_consecutive_fails = 0;
    sfm_reinit_count++;
    sfm3000BeginRecovery(micros());
  }
  return false;
}

// One-shot diagnostic — only called from setup() if sfm3000Init() fails.
static void i2cScan() {
  Serial.println(F("# I2C scan (main bus):"));
  int found = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    const uint8_t err = Wire.endTransmission();
    if (err == 0) {
      Serial.print(F("#   device found at 0x"));
      if (addr < 16) Serial.print('0');
      Serial.println(addr, HEX);
      found++;
    }
  }
  if (found == 0) {
    Serial.println(F("#   nothing responded at all — check VDD (5V), GND, "
                     "and that SDA/SCL are actually the pins Wire.begin() "
                     "is using on this board"));
  }
}

static bool sfm3000Init() {
  Wire.beginTransmission(SFM3000_I2C_ADDR);
  Wire.write(0x10);
  Wire.write(0x00);
  const uint8_t i2c_status = Wire.endTransmission();
  if (i2c_status != 0) return false;

  delay(100);  // let the first (to-be-discarded) conversion complete

  uint16_t discard;
  return sfm3000ReadRaw(discard);
}

// =============================================================================
//  SDP811 × 7  (Wire1, Qwiic bus, via PCA9548 mux) — inherited from
//  MechLung_Final (FlowTestingPY never touched this subsystem), with
//  non-blocking runtime recovery (R8) and per-channel sample ages (R15) added.
//
//  Mux channel N -> "Psens(N+1)". Channel 7 unused. Reliability: scale
//  factor read live (never hardcoded); muxSelect() checked before every
//  read attempt; all 7 channels attempted every cycle regardless of any
//  other channel's failure; consecutive-failure tracking triggers a real
//  re-init past a threshold.
//
//  Both buses use the same explicit timeout configured in setup().
// =============================================================================

static const uint8_t MUX_ADDR = 0x70;
static const uint8_t SDP_ADDR = 0x26;   // all 7 SDP811s share this address

static const int NUM_PSENS = 7;          // mux channels 0-6; channel 7 unused

static const uint8_t CMD_START_HI = 0x36;
static const uint8_t CMD_START_LO = 0x1E;  // diff. pressure, no temp comp, no averaging
static const uint8_t CMD_STOP_HI  = 0x3F;
static const uint8_t CMD_STOP_LO  = 0xF9;

static const int CONSECUTIVE_FAIL_REINIT_THRESHOLD = 5;

struct SdpSensor {
  float    pressure_pa;
  float    temp_c;
  bool     ok;
  uint16_t consecutive_fails;
  uint32_t reinit_count;   // cumulative, surfaced in the Monitor block
  uint8_t  recovery_state;
  uint32_t recovery_due_us;
  uint32_t sample_us;      // completion time of latest valid pressure read
};

enum SdpRecoveryState : uint8_t {
  SDP_RECOVERY_IDLE,
  SDP_RECOVERY_WAIT_START,
  SDP_RECOVERY_WAIT_READY,
  SDP_RECOVERY_RETRY_WAIT,
};

static const uint32_t SDP_RECOVERY_RETRY_US = 100000UL;

static SdpSensor psens[NUM_PSENS];

static bool muxSelect(uint8_t channel) {
  Wire1.beginTransmission(MUX_ADDR);
  Wire1.write(1 << channel);
  return Wire1.endTransmission() == 0;
}

static bool sdpCheckCrc(uint8_t msb, uint8_t lsb, uint8_t crc) {
  uint8_t val = 0xFF;
  val ^= msb;
  for (int b = 0; b < 8; b++) val = (val & 0x80) ? ((val << 1) ^ 0x31) : (val << 1);
  val ^= lsb;
  for (int b = 0; b < 8; b++) val = (val & 0x80) ? ((val << 1) ^ 0x31) : (val << 1);
  return val == crc;
}

static bool sdpStart() {
  Wire1.beginTransmission(SDP_ADDR);
  Wire1.write(CMD_START_HI);
  Wire1.write(CMD_START_LO);
  return Wire1.endTransmission() == 0;
}

static void sdpStop() {
  Wire1.beginTransmission(SDP_ADDR);
  Wire1.write(CMD_STOP_HI);
  Wire1.write(CMD_STOP_LO);
  Wire1.endTransmission();  // datasheet: stop may NACK harmlessly if already idle
}

static bool sdpRead(float &pressure_pa, float &temp_c) {
  uint8_t n = Wire1.requestFrom((uint8_t)SDP_ADDR, (uint8_t)9);
  if (n < 9) {
    // This path runs hundreds of times per second; do not depend on the
    // current core resetting its RX index on the next requestFrom().
    while (Wire1.available()) Wire1.read();
    return false;
  }

  uint8_t dp_msb = Wire1.read();
  uint8_t dp_lsb = Wire1.read();
  uint8_t dp_crc = Wire1.read();
  uint8_t t_msb  = Wire1.read();
  uint8_t t_lsb  = Wire1.read();
  uint8_t t_crc  = Wire1.read();
  uint8_t sf_msb = Wire1.read();
  uint8_t sf_lsb = Wire1.read();
  uint8_t sf_crc = Wire1.read();

  if (!sdpCheckCrc(dp_msb, dp_lsb, dp_crc)) return false;
  if (!sdpCheckCrc(t_msb,  t_lsb,  t_crc))  return false;
  if (!sdpCheckCrc(sf_msb, sf_lsb, sf_crc)) return false;

  int16_t raw_dp   = (int16_t)((uint16_t)dp_msb << 8 | dp_lsb);
  int16_t raw_temp = (int16_t)((uint16_t)t_msb  << 8 | t_lsb);
  int16_t raw_sf   = (int16_t)((uint16_t)sf_msb << 8 | sf_lsb);

  if (raw_sf == 0) return false;

  pressure_pa = (float)raw_dp   / (float)raw_sf;
  temp_c      = (float)raw_temp / 200.0f;
  return true;
}

static bool initPsensChannel(uint8_t channel) {
  if (!muxSelect(channel)) return false;
  delay(20);  // let the bus settle after the channel switch — boot-time only,
              // does not touch the paced read loop's speed
  sdpStop();
  delay(1);
  if (!sdpStart()) return false;
  return true;
}

static void beginPsensRecovery(uint8_t channel, uint32_t now_us) {
  SdpSensor &s = psens[channel];
  s.ok = false;
  s.reinit_count++;

  if (muxSelect(channel)) {
    sdpStop();
    s.recovery_state = SDP_RECOVERY_WAIT_START;
    s.recovery_due_us = now_us + 1000UL;
  } else {
    s.recovery_state = SDP_RECOVERY_RETRY_WAIT;
    s.recovery_due_us = now_us + SDP_RECOVERY_RETRY_US;
  }
}

// Returns true only when the channel is ready for a normal read. Every state
// transition is bounded to one short I2C transaction; mandatory waits happen
// between loop passes instead of inside delay().
static bool servicePsensRecovery(uint8_t channel, uint32_t now_us) {
  SdpSensor &s = psens[channel];
  if (s.recovery_state == SDP_RECOVERY_IDLE) return true;
  if (!timeReachedUs(now_us, s.recovery_due_us)) return false;

  if (s.recovery_state == SDP_RECOVERY_WAIT_START) {
    if (muxSelect(channel) && sdpStart()) {
      s.recovery_state = SDP_RECOVERY_WAIT_READY;
      s.recovery_due_us = now_us + 25000UL;
    } else {
      s.recovery_state = SDP_RECOVERY_RETRY_WAIT;
      s.recovery_due_us = now_us + SDP_RECOVERY_RETRY_US;
    }
    return false;
  }

  if (s.recovery_state == SDP_RECOVERY_WAIT_READY) {
    s.recovery_state = SDP_RECOVERY_IDLE;
    s.consecutive_fails = 0;
    return true;
  }

  beginPsensRecovery(channel, now_us);
  return false;
}

// One-shot diagnostic — scans Wire1 (the Qwiic/mux bus) for any responding
// address. Called from setup() if every channel fails to init, so a wiring/
// power problem on this bus shows up the same way i2cScan() surfaces one on
// the main bus for the SFM3000. Note: with the mux idle (no channel
// selected), only the mux itself (0x70) is expected to answer — the SDP811s
// sit behind it and won't ACK until a channel is selected.
static void i2cScanWire1() {
  Serial.println(F("# I2C scan (Wire1 / Qwiic / mux bus):"));
  int found = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire1.beginTransmission(addr);
    const uint8_t err = Wire1.endTransmission();
    if (err == 0) {
      Serial.print(F("#   device found at 0x"));
      if (addr < 16) Serial.print('0');
      Serial.println(addr, HEX);
      found++;
    }
  }
  if (found == 0) {
    Serial.println(F("#   nothing responded at all on Wire1 — check the "
                     "Qwiic cable into the mux board, that the mux is "
                     "powered, and that nothing upstream of it is loose"));
  } else {
    Serial.println(F("#   (expect 0x70 = mux; SDP811s at 0x26 won't ACK "
                     "here since no channel is selected)"));
  }
}

// Reads all 7 channels for one cycle. Returns the count of successful reads.
static int readAllPsens(uint32_t now_us) {
  int success_count = 0;

  for (uint8_t ch = 0; ch < NUM_PSENS; ch++) {
    SdpSensor &s = psens[ch];

    if (!servicePsensRecovery(ch, now_us)) {
      s.ok = false;
      continue;
    }

    bool read_ok = false;
    if (muxSelect(ch)) {
      read_ok = sdpRead(s.pressure_pa, s.temp_c);
    }

    s.ok = read_ok;

    if (read_ok) {
      s.sample_us = micros();
      s.consecutive_fails = 0;
      success_count++;
    } else {
      s.consecutive_fails++;
      if (s.consecutive_fails >= CONSECUTIVE_FAIL_REINIT_THRESHOLD) {
        s.consecutive_fails = 0;
        beginPsensRecovery(ch, now_us);
      }
    }
  }

  return success_count;
}

// Mean temperature across whichever channels succeeded this cycle.
static float averagePsensTemp(int success_count) {
  if (success_count == 0) return 0.0f;

  float sum = 0.0f;
  for (uint8_t ch = 0; ch < NUM_PSENS; ch++) {
    if (psens[ch].ok) sum += psens[ch].temp_c;
  }
  return sum / (float)success_count;
}

// =============================================================================
//  DAC REGISTER BOUND — NOT A TRAVEL-SAFETY LIMIT
// =============================================================================
//  This is a hardware-register bound, not a safety clamp: analogWriteResolution(12)
//  makes A0 a 12-bit register, so any write outside [0, 4095] is simply an
//  invalid value for that register. Travel safety itself is not this
//  sketch's job — it is enforced entirely downstream, by the Input scaling
//  configured in the Jrk G2 (Jrk Configuration Utility), which maps whatever
//  voltage this DAC produces onto the actuator's real safe travel regardless
//  of what firmware intended. Firmware previously duplicated that limit with
//  its own SAFE_FEEDBACK_MIN/MAX-derived clamp; see revision note R4 near
//  the top of this file for why that was removed.
//
//  A practical consequence: actuator_clamped below should be rare in normal
//  operation, since nothing here should be computing values anywhere near
//  the register's rails. If it does trip, that's a sign of a genuine bug —
//  bad geometry or calibration constants, or similar — not routine travel
//  limiting, so treat it as a fault indicator worth investigating rather
//  than expected behaviour.
// =============================================================================

static const int DAC_REG_MIN = 0;
static const int DAC_REG_MAX = 4095;

// A motion session begins in either startPreset() or startDemoSine(); both
// clear the flag before any DAC write, so it describes only the current session.
static bool actuator_clamped = false;  // sticky within the current motion session: any rail hit since the session began
static int  last_dac_out     = 0;      // actual value last written to A0

// THE ONLY function in this sketch permitted to call analogWrite(A0, ...).
static int writeActuatorDac(int dac_value) {
  const int clamped = constrain(dac_value, DAC_REG_MIN, DAC_REG_MAX);
  actuator_clamped = actuator_clamped || (clamped != dac_value);
  last_dac_out = clamped;
  analogWrite(A0, clamped);
  return clamped;
}

// =============================================================================
//  ACTUATOR POSITION FEEDBACK (pot tap) — TELEMETRY ONLY
// =============================================================================
//  CALIBRATION REQUIRED — see MechLung_Final/FlowTestingPY calibration
//  procedure notes (H hold + X hold, pair pot_raw_adc against known DAC
//  targets). Values below are carried over from FlowTestingPY's logged
//  calibration; re-calibrate for this rig if the pot wiring changes.
//  The scaled feedback value is sampled at the same 100Hz tick as the DAC
//  command and is never fed back into that command. The Jrk remains the only
//  component responsible for closed-loop actuator control.
// =============================================================================

// A second Jrk feedback-scale target, distinct from DAC_CENTRE, used only to
// give the H/X hold pair two separated points to calibrate the pot-to-DAC
// relationship against. It carries no safety meaning — the Jrk's own Input
// scaling confines the actual motion regardless of what value is requested
// here — so any value clearly different from DAC_CENTRE works; this one is
// carried over unchanged from the previous calibration.
static const int CALIBRATION_TARGET_JRK_SCALE = 1900;

static const uint8_t POT_FEEDBACK_PIN = A1;   // confirm this pin is free/wired

// VERIFY: POT_RAW_AT_CENTRE is inherited and unverified on this rig; re-derive it with the H/X hold pair before treating feedback_dac, fdbk_pct, or following error as quantitative.
static const float POT_RAW_AT_CENTRE      = 1414.0f;
// VERIFY: POT_DAC_COUNTS_PER_ADC is inherited and unverified on this rig; re-derive it with the H/X hold pair before treating feedback_dac, fdbk_pct, or following error as quantitative.
static const float POT_DAC_COUNTS_PER_ADC = 5.0118f;

static float position_follow_error = 0.0f;  // commanded - measured, diagnostic only
static int   pot_raw_adc_last      = 0;     // last raw analogRead(A1) — unfiltered

// Median-of-3 outlier filter on the pot read.
static int pot_hist[3]     = {0, 0, 0};
static int pot_hist_count  = 0;

static int medianOf3(int a, int b, int c) {
  if ((a <= b && b <= c) || (c <= b && b <= a)) return b;
  if ((b <= a && a <= c) || (c <= a && a <= b)) return a;
  return c;
}

static void resetPotFilter() {
  pot_hist[0] = pot_hist[1] = pot_hist[2] = 0;
  pot_hist_count = 0;
}

static float readPotAsDacEquivalent() {
  pot_raw_adc_last = analogRead(POT_FEEDBACK_PIN);

  pot_hist[0] = pot_hist[1];
  pot_hist[1] = pot_hist[2];
  pot_hist[2] = pot_raw_adc_last;
  if (pot_hist_count < 3) pot_hist_count++;

  const int filtered = (pot_hist_count < 3)
      ? pot_raw_adc_last
      : medianOf3(pot_hist[0], pot_hist[1], pot_hist[2]);

  return corrected_centre_dac + ((float)filtered - POT_RAW_AT_CENTRE) * POT_DAC_COUNTS_PER_ADC;
}

static void resetPositionFeedback() {
  position_follow_error = 0.0f;
  resetPotFilter();
}

// =============================================================================
//  PRESET STRUCT + CALCULATION — the stroke amplitude and timing per preset.
//  The position profile applied to these values is stepDac()'s raised-cosine
//  ramp (R12).
// =============================================================================

struct Preset {
  float q_peak_Lmin;
  float k_area;
  float a_mm;
  int   a_dac_raw;
  int   a_dac_corr;
  float t_exp_us;
  float t_insp_us;
  float period_us;
  float rr_bpm;
};

static Preset presets[4];

static float computeKarea() {
  const float r = CYLINDER_DIAMETER_MM / 2.0f;
  return (PI * r * r) / 1000.0f;   // mL of swept volume per mm of stroke
}

static int mmToDacCounts(float mm) {
  // VERIFY: This conversion assumes DAC_HALF_RANGE is on the uncorrected command scale, while cmd_pct/fdbk_pct use it on corrected DAC/A1 scales; a mismatch can shift tidal volume and peak flow by about 2.4%. Command a known DAC delta, measure piston travel with calipers, and determine which scale 1526 represents before changing the scale.
  return (int)(mm * ((float)DAC_HALF_RANGE / (ACTUATOR_STROKE_MM / 2.0f)) + 0.5f);
}

static void initPresets() {
  const float k_area      = computeKarea();
  const float gain_factor = 4095.0f / DAC_CORR_GAIN;

  const float a_mm  = V_TIDAL_ML / k_area;
  const int   a_dac = mmToDacCounts(a_mm);

  static const float q_Lmin[4] = { 10.0f, 15.0f, 20.0f, 30.0f };

  for (int i = 0; i < 4; i++) {
    const float Q_mls = q_Lmin[i] * 1000.0f / 60.0f;

    const float t_insp_s = (V_TIDAL_ML * PI) / (2.0f * Q_mls);
    const float t_exp_s  = t_insp_s * (IE_EXP_PARTS / IE_INSP_PARTS);
    const float period_s = t_exp_s + t_insp_s;

    presets[i].q_peak_Lmin = q_Lmin[i];
    presets[i].k_area      = k_area;
    presets[i].a_mm        = a_mm;
    presets[i].a_dac_raw   = a_dac;
    presets[i].a_dac_corr  = (int)((float)a_dac * gain_factor + 0.5f);
    presets[i].t_exp_us    = t_exp_s  * 1e6f;
    presets[i].t_insp_us   = t_insp_s * 1e6f;
    presets[i].period_us   = period_s * 1e6f;
    presets[i].rr_bpm      = 60.0f / period_s;
  }
}

// =============================================================================
//  BOOT-TIME GEOMETRY SUMMARY — informational only, not a safety check
// =============================================================================
//  This sketch has no visibility into what travel the Jrk G2 is currently
//  configured to permit — that configuration lives in the Jrk itself (Jrk
//  Configuration Utility, Input scaling) and firmware does not read it back.
//  So unlike the removed R4 boot-time travel check (see the note near the
//  top of this file), this print cannot tell you whether a preset's
//  commanded stroke will clip: it just states the geometry firmware computed
//  from V_TIDAL_ML and the cylinder bore, so it can be cross-checked by eye
//  against the Jrk's own configured Input scaling before a run.
// =============================================================================

static void reportGeometrySummary() {
  const int peak_cmd = corrected_centre_dac + presets[0].a_dac_corr;

  Serial.print(F("# Geometry: Vt="));
  Serial.print(V_TIDAL_ML, 0);
  Serial.print(F(" mL at bore "));
  Serial.print(CYLINDER_DIAMETER_MM, 0);
  Serial.print(F(" mm -> stroke amplitude A="));
  Serial.print(presets[0].a_mm, 1);
  Serial.print(F(" mm, peak DAC "));
  Serial.print(peak_cmd);
  Serial.print(F(" (centre "));
  Serial.print(corrected_centre_dac);
  Serial.println(F(")."));
  Serial.println(F("# Cross-check this against the Jrk G2's configured "
                   "Input scaling before running a preset — firmware does "
                   "not read that configuration back and cannot detect a "
                   "mismatch itself."));
}

// =============================================================================
//  ACTUATOR TIMING — 100Hz, matching the Jrk G2's default 10ms PID period.
//  Independent of the sensor cycle and of the log cadence.
// =============================================================================

static const uint32_t DAC_TICK_US = 10000UL;  // 100 Hz

static int      current_preset = -1;  // -1 idle, -2 demo sine, 0-3 presets
// VERIFY: phi_us remains float because changing it alone would still narrow through float preset periods and fmodf(); confirm its float-ULP resolution near preset 1's longest period is acceptable on the rig before making a coordinated double-precision change.
static float    phi_us         = 0.0f;
static uint32_t last_dac_us    = 0;
static uint32_t last_log_us    = 0;
static uint32_t last_sensor_us = 0;

static float last_feedback_dac = 0.0f;  // scaled A1 reading from the last tick

static void holdCentre() {
  writeActuatorDac(corrected_centre_dac);
}

static int stepDac(float phi) {
  const Preset &p = presets[current_preset];
  float pos_norm;

  if (phi < p.t_exp_us) {
    pos_norm = 0.5f * (1.0f - cosf(PI * phi / p.t_exp_us));
  } else {
    pos_norm = 0.5f * (1.0f + cosf(PI * (phi - p.t_exp_us) / p.t_insp_us));
  }

  const float profile_dac = corrected_centre_dac + (float)p.a_dac_corr * pos_norm;
  return writeActuatorDac((int)(profile_dac + 0.5f));
}

// The profile's volume derivative, expressed as standard L/min. Phase 0 is
// the longer expiration stroke; phase 1 is the faster inspiration stroke.
// The 2:1 timing ratio means expiration intentionally peaks at half the
// preset's named peak while inspiration reaches the named peak.
static float commandedFlowSlm(float phi, int &phase_out,
                              float &phase_peak_slm_out) {
  if (current_preset < 0) {
    phase_out = -1;
    phase_peak_slm_out = 0.0f;
    return 0.0f;
  }

  const Preset &p = presets[current_preset];
  if (phi < p.t_exp_us) {
    phase_out = 0;
    phase_peak_slm_out = p.q_peak_Lmin * (p.t_insp_us / p.t_exp_us);
    return phase_peak_slm_out * sinf(PI * phi / p.t_exp_us);
  }

  phase_out = 1;
  phase_peak_slm_out = p.q_peak_Lmin;
  return -phase_peak_slm_out *
         sinf(PI * (phi - p.t_exp_us) / p.t_insp_us);
}

static int32_t sampleAgeUs(uint32_t now_us, bool valid, uint32_t sample_us) {
  if (!valid || sample_us == 0) return -1;
  return (int32_t)(now_us - sample_us);
}

// =============================================================================
//  DEMO SINE — full-range motion demo, not physiologically meaningful.
//  Sweeps nearly the full DAC register range, DEMO_SINE_MARGIN_DAC counts
//  in from each rail. "Full-range" is now literal: with the old
//  SAFE_FEEDBACK-derived clamp removed (see revision note R4), the actual
//  motion this produces is whatever the Jrk's own configured Input scaling
//  maps this sweep onto — the Jrk, not this constant, decides how far the
//  piston actually travels. Triggered by 's'/'S'.
// =============================================================================

static const float DEMO_SINE_PERIOD_US = 3.0e6f;  // 3s/cycle
static const int   DEMO_SINE_MARGIN_DAC = 100;     // keep a small margin off the register rails

static int demo_sine_dac_min = 0;
static int demo_sine_dac_max = 4095;

static int stepDemoSine(float phi) {
  const float half_range = (float)(demo_sine_dac_max - demo_sine_dac_min) / 2.0f;
  const float centre     = (float)(demo_sine_dac_max + demo_sine_dac_min) / 2.0f;
  const float pos_norm   = sinf(2.0f * PI * phi / DEMO_SINE_PERIOD_US);

  const float dac_out_unclamped = centre + half_range * pos_norm;
  return writeActuatorDac((int)(dac_out_unclamped + 0.5f));
}

// =============================================================================
//  SERIAL COMMAND HANDLER
// =============================================================================

static uint32_t seq = 0;  // increments once per logged row
static bool monitor_enabled = true;

// The watchdog is deliberately opt-in: only receipt of the logger's internal
// heartbeat arms it. Serial Monitor users can still start an autonomous run,
// while logger-controlled runs fail to centre if the logger disappears.
static const uint32_t HOST_HEARTBEAT_TIMEOUT_MS = 3000UL;
static bool host_watchdog_armed = false;
static uint32_t last_host_heartbeat_ms = 0;

static void printBanner();

static void startPreset(int idx) {
  current_preset = constrain(idx, 0, 3);
  phi_us      = 0.0f;
  seq         = 0;
  actuator_clamped = false;
  const uint32_t run_start_us = micros();
  last_dac_us = run_start_us;
  last_log_us = run_start_us;
  last_sensor_us = run_start_us;
  resetPositionFeedback();
  last_feedback_dac = readPotAsDacEquivalent();
  position_follow_error = (float)last_dac_out - last_feedback_dac;

  const Preset &p = presets[current_preset];
  Serial.print(F("# PRESET_START preset="));
  Serial.print(current_preset + 1);
  Serial.print(F(" Qpeak_Lmin="));  Serial.print(p.q_peak_Lmin, 0);
  Serial.print(F(" RR_BPM="));      Serial.print(p.rr_bpm, 2);
  Serial.print(F(" A_mm="));        Serial.print(p.a_mm, 2);
  Serial.print(F(" Vt_mL="));       Serial.print(V_TIDAL_ML, 0);
  Serial.print(F(" T_exp_s="));     Serial.print(p.t_exp_us  / 1e6f, 3);
  Serial.print(F(" T_insp_s="));    Serial.print(p.t_insp_us / 1e6f, 3);
  Serial.print(F(" log_Hz="));      Serial.print(LOG_RATE_HZ);
  Serial.println();
}

static void startDemoSine() {
  current_preset = -2;
  phi_us      = 0.0f;
  seq         = 0;
  actuator_clamped = false;
  const uint32_t run_start_us = micros();
  last_dac_us = run_start_us;
  last_log_us = run_start_us;
  last_sensor_us = run_start_us;
  resetPositionFeedback();
  last_feedback_dac = readPotAsDacEquivalent();
  position_follow_error = (float)last_dac_out - last_feedback_dac;
  Serial.print(F("# DEMO_SINE_START period_s="));
  Serial.print(DEMO_SINE_PERIOD_US / 1e6f, 2);
  Serial.print(F(" dac_range=["));
  Serial.print(demo_sine_dac_min);
  Serial.print(F(", "));
  Serial.print(demo_sine_dac_max);
  Serial.println(F("] (actual travel set by the Jrk's Input scaling, not by this range)"));
}

static void goIdleHold() {
  current_preset = -1;
  host_watchdog_armed = false;
  resetPositionFeedback();
  holdCentre();
  Serial.println(F("# HOLD centre (DAC_CENTRE), idle. Logging stopped."));
}

static void goCalibrationTarget() {
  current_preset = -1;
  resetPositionFeedback();
  const int target = applyDacCorrection(CALIBRATION_TARGET_JRK_SCALE);
  writeActuatorDac(target);
  Serial.print(F("# CALIBRATION_TARGET jrk_scale_target="));
  Serial.println(CALIBRATION_TARGET_JRK_SCALE);
}

static void toggleMonitor() {
  monitor_enabled = !monitor_enabled;
  Serial.print(F("# MONITOR "));
  Serial.println(monitor_enabled ? F("on") : F("off (DATA rows only)"));
}

static void handleSerial() {
  while (Serial.available()) {
    const char c = (char)Serial.read();

    switch (c) {
      case '1': case '2': case '3': case '4':
        startPreset(c - '1');
        break;
      case 's': case 'S':
        startDemoSine();
        break;
      case 'H': case 'h': case '0':
        goIdleHold();
        break;
      case 'X': case 'x':
        goCalibrationTarget();
        break;
      case 'm': case 'M':
        toggleMonitor();
        break;
      case '?':
        printBanner();
        Serial.println(F("# READY_QUERY"));
        break;
      case '!':
        last_host_heartbeat_ms = millis();
        host_watchdog_armed = true;
        break;
      default:
        break;  // ignore stray/whitespace bytes outside a command
    }
  }
}

// =============================================================================
//  SERIAL OUTPUT — Monitor block (throttled, human-readable)
// =============================================================================

static const uint32_t MONITOR_PRINT_INTERVAL_MS = 300;  // ~3.3 Hz
static uint32_t last_monitor_print_ms = 0;

static void printMonitorBlock(uint32_t now_ms, int dac_out, float actual_dac_equiv,
                              float cmd_pct, float fdbk_pct,
                              int psens_ok_count, float psens_temp_avg) {
  Serial.println(F("--------------------------------------------------"));

  Serial.print(F(" t=")); Serial.print(now_ms / 1000.0f, 1); Serial.print(F("s  preset="));
  if (current_preset == -2) {
    Serial.println(F("demo-sine"));
  } else if (current_preset == -1) {
    Serial.println(F("idle/hold"));
  } else {
    Serial.print(current_preset + 1);
    Serial.print(F(" (Q="));
    Serial.print(presets[current_preset].q_peak_Lmin, 0);
    Serial.println(F(" L/min)"));
  }

  Serial.print(F(" Flow      : "));
  if (flow_sensor_ok) {
    Serial.print(flow_slm, 2);
    Serial.print(F(" slm"));
    if (sfm_reinit_count) {
      Serial.print(F("   (reinits: ")); Serial.print(sfm_reinit_count); Serial.print(')');
    }
    Serial.println();
  } else {
    Serial.println(F("-- sensor not responding (check wiring / I2C addr 0x40)"));
  }

  Serial.print(F(" Pressure  : ")); Serial.print(psens_ok_count); Serial.print(F("/7 ok, avg temp "));
  Serial.print(psens_temp_avg, 1); Serial.print(F(" C"));
  uint32_t total_reinits = 0;
  for (uint8_t ch = 0; ch < NUM_PSENS; ch++) total_reinits += psens[ch].reinit_count;
  if (total_reinits) { Serial.print(F(", reinits ")); Serial.print(total_reinits); }
  Serial.println();

  Serial.print(F(" Command   : ")); Serial.print(dac_out);
  Serial.print(F(" DAC  (")); Serial.print(cmd_pct, 0); Serial.println(F("% of stroke)"));

  Serial.print(F(" Feedback  : ")); Serial.print(actual_dac_equiv, 0);
  Serial.print(F(" DAC  (")); Serial.print(fdbk_pct, 0); Serial.println(F("% of stroke)"));

  Serial.print(F(" Follow err: ")); Serial.print(position_follow_error, 1);
  Serial.println(F(" counts"));
  Serial.print(F(" Clamped   : ")); Serial.println(actuator_clamped ? F("YES") : F("no"));
}

static void printBanner() {
  Serial.println(F("# ================================================="));
  Serial.println(F("# MechLung — full sensor suite + Jrk-scaled actuator control"));
  Serial.print  (F("# DATA line @ "));
  Serial.print(LOG_RATE_HZ);
  Serial.println(F(" Hz (only while a run is active): "
                   "seq,millis,flow_slm,flow_ok,"
                   "flow_age_us,Psens1_pa..Psens7_pa,"
                   "psens_temp_c_avg,Psens1_ok..Psens7_ok,"
                   "Psens1_age_us..Psens7_age_us,cmd_dac,feedback_dac,"
                   "cmd_pct,fdbk_pct,target_flow_slm,target_peak_slm,"
                   "phase,preset,clamped"));
  Serial.println(F("# Commands: 1-4 preset | s demo sine | H hold | "
                   "X calibration hold | m toggle monitor | ? this "
                   "banner"));
  Serial.println(F("# Readable summary (a few times/sec): open Tools > Serial "
                   "Monitor instead (close any logging script first — only "
                   "one program can hold the serial port at a time)."));
  Serial.println(F("# ================================================="));
}

// =============================================================================
//  setup()
// =============================================================================

void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && (millis() - t0 < 2000));

  printBanner();
  Serial.println(F("# (MechLung_Final sensors, FlowTestingPY actuator/feedback; "
                   "travel safety enforced by the Jrk G2's own Input scaling)"));

  // ---- Actuator first, unconditionally, before anything I2C-related ----
  // Neither the SFM3000 nor the SDP811 array should be able to block the
  // actuator's first command, so all actuator setup happens before any
  // Wire.begin() call.
  initPresets();
  corrected_centre_dac = applyDacCorrection(DAC_CENTRE);

  // DAC register bound — see the note above writeActuatorDac(): this is a
  // hardware-register limit, not travel safety. Travel safety is the Jrk
  // G2's job, via its own configured Input scaling; this sketch does not
  // enforce or know that range, so there is nothing to compute here.
  Serial.print(F("# DAC register range: ["));
  Serial.print(DAC_REG_MIN); Serial.print(F(", "));
  Serial.print(DAC_REG_MAX); Serial.println(F("] (hardware limit only — "
                             "travel safety is enforced by the Jrk G2's "
                             "configured Input scaling, not by firmware)"));

  demo_sine_dac_min = DAC_REG_MIN + DEMO_SINE_MARGIN_DAC;
  demo_sine_dac_max = DAC_REG_MAX - DEMO_SINE_MARGIN_DAC;

  Serial.print(F("# Demo sine DAC range: ["));
  Serial.print(demo_sine_dac_min); Serial.print(F(", "));
  Serial.print(demo_sine_dac_max); Serial.println(F("]"));

  reportGeometrySummary();

  analogWriteResolution(12);
  analogReadResolution(12);

  holdCentre();
  Serial.println(F("# Holding DAC_CENTRE — settling 2s..."));
  delay(2000);

  // ---- Sensors second, and unable to block the sketch ----
  // Both Wire buses are brought up (recovery, begin, clock, timeout) before
  // either sensor is touched. Only actuator setup runs earlier than this.
  i2cBusRecovery();       // clear any SDA-held-low left over from a previous upload
  Wire.begin();
  Wire.setClock(200000);
  Wire.setWireTimeout(I2C_TRANSACTION_TIMEOUT_US, false);
  delay(100);

  i2cBusRecovery1();      // clear any SDA1-held-low left over from a previous upload/reset
  Wire1.begin();
  Wire1.setClock(400000); // stuck-bus recovery is handled by i2cBusRecovery1() above, not by clock speed
  Wire1.setWireTimeout(I2C_TRANSACTION_TIMEOUT_US, false);

  sfm_ok = sfm3000Init();
  sfm_recovery_state = SFM_RECOVERY_RETRY_WAIT;
  sfm_recovery_due_us = micros() + SFM_RETRY_INTERVAL_US;
  Serial.print(F("# SFM3000 init: "));
  Serial.println(sfm_ok ? F("OK") : F("FAILED (check wiring / addr 0x40) — "
                                      "continuing without flow data"));
  if (!sfm_ok) i2cScan();

  int psens_init_ok_count = 0;
  for (uint8_t ch = 0; ch < NUM_PSENS; ch++) {
    psens[ch].reinit_count = 0;
    psens[ch].recovery_state = SDP_RECOVERY_IDLE;
    psens[ch].recovery_due_us = 0;
    bool ok = initPsensChannel(ch);
    Serial.print(F("# Psens")); Serial.print(ch + 1);
    Serial.print(F(" (mux ch ")); Serial.print(ch); Serial.print(F("): "));
    Serial.println(ok ? F("OK") : F("FAILED"));
    if (ok) psens_init_ok_count++;
    delay(25);
  }
  if (psens_init_ok_count == 0) i2cScanWire1();

  last_dac_us = micros();
  last_monitor_print_ms = millis();

  Serial.println(F("# Ready. Holding centre. Send 1-4 for a preset, s for "
                   "a full-range demo sine, H to hold/idle, X to hold the "
                   "calibration target."));
}

// =============================================================================
//  loop()
// =============================================================================

void loop() {
  static int      last_ok_count  = 0;
  static float    last_temp_avg  = 0.0f;

  handleSerial();

  const uint32_t now_ms = millis();
  if (host_watchdog_armed &&
      (uint32_t)(now_ms - last_host_heartbeat_ms) >= HOST_HEARTBEAT_TIMEOUT_MS) {
    const bool run_was_active = current_preset != -1;
    host_watchdog_armed = false;
    if (run_was_active) {
      goIdleHold();
      Serial.println(F("# HOST_WATCHDOG logger heartbeat lost; actuator returned to centre."));
    }
  }

  const uint32_t now_us = micros();

  // ── ACTUATOR — independent 100Hz tick ────────────────────────────────────
  if ((uint32_t)(now_us - last_dac_us) >= DAC_TICK_US) {
    const uint32_t elapsed = now_us - last_dac_us;
    last_dac_us = now_us;

    if (current_preset == -2) {
      phi_us = fmodf(phi_us + (float)elapsed, DEMO_SINE_PERIOD_US);
      stepDemoSine(phi_us);
    } else if (current_preset >= 0) {
      phi_us = fmodf(phi_us + (float)elapsed, presets[current_preset].period_us);
      stepDac(phi_us);
    } else {
      // Idle/hold/calibration hold: don't reissue a command, just keep
      // reading position feedback so H/X calibration holds stay live.
    }

    last_feedback_dac = readPotAsDacEquivalent();
    position_follow_error = (float)last_dac_out - last_feedback_dac;
  }

  // ── SENSORS — one scan per actuator/log tick. This runs after the DAC
  //    update and before the DATA row, so that row always carries the newest
  //    available flow/pressure set. Per-sensor ages expose sequential skew.
  if ((uint32_t)(now_us - last_sensor_us) >= SENSOR_CYCLE_US) {
    last_sensor_us = now_us;
    sfm3000Service(now_us);
    last_ok_count = readAllPsens(now_us);
    last_temp_avg = averagePsensTemp(last_ok_count);
  }

  // VERIFY: These percentages assume DAC_HALF_RANGE applies equally to corrected DAC commands and A1-derived feedback, while mmToDacCounts() uses it as a travel scale; a mismatch can shift tidal volume and peak flow by about 2.4%. Command a known DAC delta, measure piston travel with calipers, and determine which scale 1526 represents before treating these percentages as quantitative.
  const float cmd_pct  = 100.0f * (float)(last_dac_out - corrected_centre_dac) / (float)DAC_HALF_RANGE;
  const float fdbk_pct = 100.0f * (last_feedback_dac - (float)corrected_centre_dac) / (float)DAC_HALF_RANGE;
  int breath_phase;
  float target_peak_slm;
  const float target_flow_slm = commandedFlowSlm(
      phi_us, breath_phase, target_peak_slm);

  // ── LOGGING — one merged CSV row at a FIXED LOG_RATE_HZ cadence (R1),
  //    only while a run (preset or demo sine) is active. Idle/calibration
  //    hold stays silent on this line, same as MechLung_Final's original
  //    gate. Command and feedback counts are sampled by the actuator tick
  //    immediately before this row whenever both 100Hz schedules are due.
  //
  //    Deadline handling (R16): last_log_us advances by exactly one interval
  //    so the cadence stays phase-locked. If that leaves the row a full
  //    interval or more overdue (>=, not >, so the exact-boundary case at two
  //    elapsed intervals is included), the backlog is skipped by
  //    resynchronizing to now_us rather than emitting a catch-up row from the
  //    same sensor scan. Unsigned subtraction keeps this safe across micros()
  //    wraparound.
  if (current_preset != -1 &&
      (uint32_t)(now_us - last_log_us) >= LOG_INTERVAL_US) {
    last_log_us += LOG_INTERVAL_US;
    if ((uint32_t)(now_us - last_log_us) >= LOG_INTERVAL_US) last_log_us = now_us;
    const uint32_t row_us = micros();
    const uint32_t row_ms = millis();

    Serial.print(F("DATA,"));
    Serial.print(seq);                       Serial.print(',');
    Serial.print(row_ms);                    Serial.print(',');
    Serial.print(flow_slm, 3);               Serial.print(',');
    Serial.print(flow_sensor_ok ? 1 : 0);    Serial.print(',');
    Serial.print(sampleAgeUs(row_us, flow_sensor_ok, flow_sample_us));
    Serial.print(',');
    for (uint8_t ch = 0; ch < NUM_PSENS; ch++) {
      Serial.print(psens[ch].pressure_pa, 3);
      Serial.print(',');
    }
    Serial.print(last_temp_avg, 2);          Serial.print(',');
    for (uint8_t ch = 0; ch < NUM_PSENS; ch++) {
      Serial.print(psens[ch].ok ? 1 : 0);
      Serial.print(',');
    }
    for (uint8_t ch = 0; ch < NUM_PSENS; ch++) {
      Serial.print(sampleAgeUs(row_us, psens[ch].ok, psens[ch].sample_us));
      Serial.print(',');
    }
    Serial.print(last_dac_out);              Serial.print(',');
    Serial.print(last_feedback_dac, 2);      Serial.print(',');
    Serial.print(cmd_pct, 2);                Serial.print(',');
    Serial.print(fdbk_pct, 2);               Serial.print(',');
    Serial.print(target_flow_slm, 3);        Serial.print(',');
    Serial.print(target_peak_slm, 3);        Serial.print(',');
    Serial.print(breath_phase);              Serial.print(',');
    Serial.print(current_preset);            Serial.print(',');
    Serial.println(actuator_clamped ? 1 : 0);

    seq++;
  }

  // ── MONITOR — throttled, independent of the tick and of the log gate,
  //    so it still shows live status during idle/calibration holds. Can be
  //    silenced with 'm' when the extra bytes are competing with DATA rows.
  if (monitor_enabled &&
      (uint32_t)(now_ms - last_monitor_print_ms) >= MONITOR_PRINT_INTERVAL_MS) {
    last_monitor_print_ms = now_ms;
    printMonitorBlock(now_ms, last_dac_out, last_feedback_dac,
                      cmd_pct, fdbk_pct, last_ok_count, last_temp_avg);
  }
}
