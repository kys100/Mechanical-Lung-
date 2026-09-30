# Flow reference and calibration

Piston displacement gives geometric **local L/min**. SFM3000 air/N2 scaling gives
standard L/min at 293.15 K and 1013 mbar. The historical wire target names retain
`slm` for positional compatibility; DATA2 documents their local basis. No ambient
conditions are assumed. Supply both `--gas-temperature-c` and
`--absolute-pressure-mbar` from measurements, or targets remain unscored:

`Q_standard = Q_local * (P_local/1013.0) * (293.15/(T_c+273.15))`

Temperature must be above absolute zero and pressure positive; both must be
finite. The conversion preserves sign. Segmentation uses the resolved standard
target when available and otherwise the nominal geometric magnitude as a
threshold heuristic. Missing conditions produce `flow_reference_unresolved`,
not MISS. Record gas and conditions; the existing factor 140 assumes air/N2.

No physical constants were recalibrated: DAC centre 1450, half range 1526,
correction offset 49/gain 4002, 300-mm actuator, 115-mm bore, 700-mL geometry,
2:1 expiration:inspiration timing, pot centre 1414 and slope 5.0118, calibration
point 1900. The unresolved corrected-versus-uncorrected DAC scale must be measured
using H/X, known command deltas and independent travel measurement before changes.
The software feedback remains diagnostic only; Jrk travel configuration is not
read or changed here. Do not infer actual delivered volume from command geometry.

SFM reads now validate a third CRC byte (poly 0x31, init 0x00; BEEF -> 13).
SDP retains init 0xFF (BEEF -> 92); command 361E includes differential-pressure
temperature compensation without averaging. Two-byte SFM reads were permitted;
CRC adds integrity checking. Recovery retries cannot fix every sensor condition,
including conditions requiring power cycling.

References: Sensirion SFM3000 datasheet and SFM-04 CRC application note,
https://sensirion.com/media/documents/1E3CD1FF/6165AFE4/Sensirion_GF_AN_SFM-04_CRC_Checksum_D1.pdf.
Physical validation is tracked separately in hardware-validation-results.json.

`cmd_pct` and `fdbk_pct` are normalized to the inherited **half-stroke DAC scale**:
100 × (corrected DAC value − corrected centre) / 1526. They are not measured
percentages of the full stroke. The actuator plot labels this normalization.
