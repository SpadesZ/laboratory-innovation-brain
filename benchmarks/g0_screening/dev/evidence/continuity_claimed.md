title: Re-measurement note on a flat series resistance
doi: 10.1000/lab-brain-dev-003
authors: R. Kuo; A. Lin
venue: Journal of Demonstration Photonics
year: 2026

# 1. Introduction

This note accompanies a locked development fixture and describes no real device.

# 2. Method

Capacitance-voltage and impedance measurements were repeated on a probe station at room
temperature, after an earlier sweep on the same arm looked wrong.

# 3. Observations

The junction capacitance fell with reverse bias as designed, from 0.515 to 0.345 pF/mm.

The series resistance stayed several times above the design value and did not change across
the reverse-bias sweep.

The layout review checklist states that contact continuity was verified on both terminals before
tape-out.

# 4. Extraction log

```log
2026-09-21 10:02:11 INFO  extracted cj_per_mm=0.515 unit=pF/mm
2026-09-21 10:02:12 WARN  contact_resistance_term unavailable; rs_per_mm reported uncorrected
```
