title: Bias-dependent junction capacitance and series resistance in a lateral PN phase shifter
doi: 10.1000/lab-brain-demo-001
authors: R. Kuo; A. Lin; M. Sato
venue: Journal of Demonstration Photonics
year: 2026

# 1. Introduction

This report records a measured discrepancy between two process splits of the same lateral PN
phase shifter. It exists as a locked benchmark fixture and describes no real device.

# 2. Method

Capacitance-voltage and impedance measurements were taken on a probe station at room
temperature. The extraction follows the small-signal model described in the appendix.

Wafer identifier and implant dose were not recorded by the measurement script.

# 3. Bias dependence

Reverse bias increased from 0 to -2 V. The junction capacitance decreased from 0.515 to 0.345 pF/mm.

The series resistance did not follow the expected trend across the same sweep. This is the
anomaly the report is about, and it is the reason both splits were re-measured.

Table 1. Extracted small-signal parameters for both splits.

| Bias | Cj | Rs | Split |
| [V] | [pF/mm] | [ohm.mm] | [-] |
| 0 | 0.515 | 12.4 | A |
| -2 | 0.345 | 12.6 | A |
| 0 | 0.518 | 18.9 | B |
| -2 | 0.347 | 19.1 | B |

Fig. 2. Junction capacitance versus reverse bias for splits A and B.

The two capacitance curves in Figure 2 are indistinguishable within measurement uncertainty,
while the series resistance differs by roughly fifty per cent between the splits. A depletion
effect alone cannot produce that combination, because it would move both quantities together.

# 4. Extraction log

```log
2026-09-18 09:14:02 INFO  loaded sweep bias=0.0:-2.0 step=0.1
2026-09-18 09:14:03 INFO  extracted cj_per_mm=0.515 unit=pF/mm
2026-09-18 09:14:03 WARN  contact_resistance_term unavailable; rs_per_mm reported uncorrected
2026-09-18 09:14:04 INFO  extraction complete points=21
```

# 5. Long discussion

The remainder of this section exists so the fixture contains one legitimately oversized evidence
unit, and it deliberately reads as a single continuous argument rather than as separable claims.
The measured behaviour is consistent with a contact-resistance contribution that does not vary
with reverse bias, which would leave the depletion capacitance untouched while adding a constant
term to the series resistance. A mesh artefact in the simulated comparison would produce a
different signature, because it would perturb the capacitance at the bias points where the
depletion edge moves fastest rather than uniformly across the sweep. A doping-profile difference
between the splits would move both quantities together, which the table does not show. An
instrumentation offset would appear on both splits equally and would not survive the re-measure
that was performed on a second probe station. The remaining candidate is a process-dependent
contact resistance, and discriminating it from the mesh artefact requires either a
transmission-line measurement on the same wafer or a mesh-sensitivity sweep on the simulated
structure. Neither has been performed at the time of writing, so this report records competing
explanations rather than a confirmed root cause, and the extraction log above notes that the
contact-resistance term was unavailable to the script that produced the table. That last point
matters more than it appears to, because it means the reported series resistance is uncorrected
and the fifty per cent difference could in principle be an artefact of the correction being
absent rather than of the devices differing. Resolving that requires the raw impedance arrays,
which are stored separately and are not part of this report.
