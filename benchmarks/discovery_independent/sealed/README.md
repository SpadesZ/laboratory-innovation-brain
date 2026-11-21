# Round 5 sealed hidden worlds

Sealed world set for the independent hidden-world evaluation
(`docs/evaluation/discovery-independent-evaluation-protocol.md`, step T3). This directory holds
only the encrypted archive and the public commitments. No world content is public.

| Item | Value |
|---|---|
| Author role | `world_author` (W) |
| Worlds (cases) | 58 |
| Catalog ref | `sp.ring_drift_loss.discovery@0.1.0` |
| Catalog digest | `sha256:69c86963d6e1ae31832208530654539a9283bded6638cad8f0877848553d9119` |
| Motivating experiment | `baseline` |
| Commitments root | `sha256:839ac0110308102f990c1d2e9e5e246600c310f7adb71b59eeaf9c28db2dcf8b` |
| Encrypted archive | `round5-hidden-worlds.tar.gz.enc` |
| Archive SHA-256 | `b23db527e50cf58f5e0a7d5a550b612fd8b0f4a274eaf6dbb5fa89693ca2fe83` |

Per-category counts are not published: the protocol keeps categories off the engine side until
the reveal (T6).

## Files

- `round5-commitments.json`: the per-case commitments (opaque case ids, from 32-byte salts) and
  their root, as produced by `lab_brain.discovery_eval.hidden_worlds.seal`. Public at T3.
- `round5-hidden-worlds.tar.gz.enc`: AES-256-CBC (PBKDF2, 200000 iterations, salted) archive of
  the author's secret directory: the plaintext world file, the sealed file (salts, truth), the
  engine package for V, the salts, the sensitivity generator and the physics rationale.

## Decrypting (Owner holds the key)

The key is not in the repository. With the key file from the Owner:

```
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass file:KEYFILE \
  -in round5-hidden-worlds.tar.gz.enc | tar xzf - -C OUTSIDE_THE_REPOSITORY
```

Extract outside the repository: the loader refuses a non-example hidden set inside it. V then
verifies the engine package and the reveal against `round5-commitments.json`
(`parse_engine_package`, `reveal`).

## Information barrier kept by W

W read only: the protocol document; `src/lab_brain/discovery_eval/hidden_worlds.py`;
`benchmarks/discovery_independent/hidden-worlds.schema.json` (first lines) and
`example.hidden-worlds.json`; and the catalog interface. For the catalog W read
`src/lab_brain/discovery/catalog.py`, the record types in `src/lab_brain/discovery/model.py`
(the experiment, entry and mechanism-class definitions), the protocol defaults' names in
`src/lab_brain/discovery/protocol.py` (grep), the import lines of
`scripts/discovery_independent_eval.py` (to find the loader), the module docstring and a
function-name listing of `src/lab_brain/domains/silicon_photonics/discovery_catalog.py`, and a
data dump of `ring_catalog()` (experiments, entries, units, sigmas, costs, declared classes,
ranges, tables, priors). W did not read the bodies of that module's functions, its development
worlds, `src/lab_brain/discovery/worlds.py`, `src/lab_brain/discovery_safety/`, any
`scripts/discovery_safety_*`, any `docs/reports/discovery-*` or `docs/audit/discovery-*`, any
discovery or safety test, or any other branch. W did not run any arm or engine on the worlds.

Tabulated effects were derived from explicit physical models of a silicon microring written by W
(formulas, parameters and literature-typical magnitudes are inside the archive). Whether a
stationary tabulated world is separable from every catalog hypothesis was decided by the
validator's own aliasing check, not by tuning against any system.

## Limitation: procedural, not institutional, independence

W is an AI model of the same family as the system's developers, run in a separately briefed
session. The barrier above is procedural (what was read and not read), not institutional
independence; the protocol's requirement of different people and at least two world authors is
not met by this set alone.
