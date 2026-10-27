"""Sealing evaluator truth by commitment: publish the hash before the run, reveal after it.

    commitment(case) = SHA-256(b"g0-eval/commit@1\\x00" || salt || canonical_json({case_id, truth}))
    root             = SHA-256(canonical_json({case_id: commitment, ...}))

The salt is 32 random bytes per case, drawn by the evaluator when sealing and kept with the truth.
Without it a short truth (one cause out of five) could be recovered from its commitment by trying
every candidate; with it the commitment reveals nothing, so the PUBLIC repository may hold the
commitments file and nothing else. The sealed truth (truth + salts) stays with the evaluator,
outside the repository, and is handed to the scorer by path only at scoring time.

`canonical_json` is the repository's restricted RFC 8785 profile (`core/canonical_json.py`): it
refuses floats, so truth is written with strings, integers and booleans -- two processes agreeing
on the content then agree on the bytes, and a re-serialised truth file still verifies.

`verify_reveal` is what the scorer runs before it reads a single answer: the revealed case set must
equal the committed set exactly, and every case's recomputed commitment must match. Any mismatch
-- an edited answer, a changed salt, a case added or dropped after the freeze -- raises
`CommitmentMismatch` and nothing is scored.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lab_brain.core.canonical_json import canonical_bytes, canonical_hash
from lab_brain.evaluation.packages import COMMITMENTS_KIND, GENERATOR_KIND, TRUTH_KIND

DOMAIN = b"g0-eval/commit@1\x00"
SCHEME = "sha256(domain || salt || canonical_json({case_id, truth})); root = sha256(canonical_json)"


class CommitmentMismatch(ValueError):
    """The revealed truth does not match what was committed before evaluation."""


@dataclass(frozen=True)
class SealedTruth:
    suite: str
    #: case id -> {"salt": hex, "truth": {...}}
    cases: Mapping[str, Mapping[str, Any]]

    def truth(self) -> dict[str, Mapping[str, Any]]:
        return {cid: entry["truth"] for cid, entry in self.cases.items()}


def commitment(case_id: str, truth: Mapping[str, Any], salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    if len(salt) < 16:
        raise ValueError(f"{case_id}: a salt shorter than 16 bytes does not hide a short answer")
    body = canonical_bytes({"case_id": case_id, "truth": dict(truth)})
    return hashlib.sha256(DOMAIN + salt + body).hexdigest()


def commitment_root(commitments: Mapping[str, str]) -> str:
    return canonical_hash(dict(commitments))


def seal(data: Mapping[str, Any]) -> dict[str, Any]:
    """Give every case of an evaluator truth document a fresh random salt (kept if present)."""
    if data.get("kind") != TRUTH_KIND:
        raise ValueError(f"not an evaluator truth document ({TRUTH_KIND})")
    cases = {
        cid: {"salt": entry.get("salt") or secrets.token_hex(32), "truth": entry["truth"]}
        for cid, entry in data["cases"].items()
    }
    return {"kind": TRUTH_KIND, "suite": data["suite"], "cases": cases}


def load_sealed_truth(path: Path) -> SealedTruth:
    data = json.loads(path.read_text(encoding="utf-8"))
    kind = data.get("kind") if isinstance(data, Mapping) else None
    if kind == GENERATOR_KIND:
        raise ValueError(f"{path.name} is a generator package, not sealed truth")
    if kind != TRUTH_KIND:
        raise ValueError(f"{path.name}: kind {kind!r} is not {TRUTH_KIND}")
    for cid, entry in data["cases"].items():
        if set(entry) != {"salt", "truth"} or not isinstance(entry["truth"], Mapping):
            raise ValueError(f"{cid}: a sealed case is exactly {{salt, truth}}")
    return SealedTruth(suite=data["suite"], cases=data["cases"])


def commitments_document(sealed: SealedTruth) -> dict[str, Any]:
    """The public half: one hash per case and their root. No salt, no answer."""
    cases = {
        cid: commitment(cid, entry["truth"], entry["salt"])
        for cid, entry in sorted(sealed.cases.items())
    }
    return {
        "kind": COMMITMENTS_KIND,
        "suite": sealed.suite,
        "scheme": SCHEME,
        "cases": cases,
        "root": commitment_root(cases),
    }


def verify_reveal(sealed: SealedTruth, committed: Mapping[str, str], root: str) -> None:
    """Refuse unless the revealed truth is exactly what was committed, case for case."""
    if commitment_root(committed) != root:
        raise CommitmentMismatch("the commitment list does not hash to the frozen root")
    missing = sorted(set(committed) - set(sealed.cases))
    extra = sorted(set(sealed.cases) - set(committed))
    if missing or extra:
        raise CommitmentMismatch(f"revealed case set differs: missing {missing}, extra {extra}")
    bad = sorted(
        cid
        for cid, entry in sealed.cases.items()
        if commitment(cid, entry["truth"], entry["salt"]) != committed[cid]
    )
    if bad:
        raise CommitmentMismatch(f"revealed truth does not match its commitment for {bad}")


#: Where an operator may name the sealed truth instead of passing `--truth`.
TRUTH_ENV = "LAB_BRAIN_G0_EVAL_TRUTH"


def truth_location(
    given: str | None, environ: Mapping[str, str], *, repo: Path, allow_in_repo: bool
) -> Path:
    """The sealed truth's path: `--truth`, else `$LAB_BRAIN_G0_EVAL_TRUTH`. Refused when it lies
    inside the (public) repository, unless the operator says it is synthetic test material."""
    raw = given or environ.get(TRUTH_ENV)
    if not raw:
        raise ValueError(f"name the sealed truth with --truth or ${TRUTH_ENV}")
    path = Path(raw).expanduser().resolve()
    if path.is_relative_to(repo.resolve()) and not allow_in_repo:
        raise ValueError(
            f"{path} is inside the repository; sealed truth is kept outside it "
            "(pass --allow-truth-in-repo only for synthetic test material)"
        )
    return path
