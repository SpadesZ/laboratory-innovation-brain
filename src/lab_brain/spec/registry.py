"""Loaders for the Normative Statement Registry (§23.6) and milestone catalog (§26.1).

Division of responsibility, per SAI 3.3 §23.5:

  (1) machine-checkable  -- registry internal consistency. Enforced by T-SPEC-002.
  (2) human-checkable    -- "every hard MUST in the prose reached the registry".
                            This cannot be derived from prose by a linter. It is a
                            review gate producing docs/spec_coverage_audit/<milestone>.md.

Passing T-SPEC-002 therefore does NOT license the conclusion that the registry is
complete. That inference is explicitly prohibited by §23.5.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

from lab_brain.spec.outcome_plugin import GATE_ENV_VARS
from lab_brain.spec.parser import repo_root

NormativeLevel = Literal["MUST", "SHOULD", "MAY"]
MilestoneStatus = Literal["NOT_STARTED", "IN_PROGRESS", "DONE", "DEFERRED"]

_VALID_LEVELS: frozenset[str] = frozenset({"MUST", "SHOULD", "MAY"})
_VALID_STATUSES: frozenset[str] = frozenset({"NOT_STARTED", "IN_PROGRESS", "DONE", "DEFERRED"})


class RegistryError(RuntimeError):
    """The registry or milestone catalog is structurally invalid."""


@dataclass(frozen=True)
class NormativeStatement:
    """One registered hard normative statement."""

    key: str
    section: str
    level: NormativeLevel
    requirement_id: str
    tests: tuple[str, ...]
    deferred_rationale: str | None = None
    review_at: str | None = None
    #: Identifier of a docs/spec_issues/ record, when this entry rests on a contested
    #: reading of the spec or on an indirect requirement mapping. AGT-015 forbids an agent
    #: from settling such a question itself, so the open question is carried as data that
    #: CI can verify rather than as a code comment.
    spec_issue: str | None = None

    @property
    def is_deferred(self) -> bool:
        return self.deferred_rationale is not None


@dataclass(frozen=True)
class NormativeStatementRegistry:
    path: Path
    schema_version: int
    spec_version: str
    statements: tuple[NormativeStatement, ...]

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(statement.key for statement in self.statements)

    def by_requirement(self, requirement_id: str) -> tuple[NormativeStatement, ...]:
        return tuple(s for s in self.statements if s.requirement_id == requirement_id)

    def sections(self) -> frozenset[str]:
        return frozenset(statement.section for statement in self.statements)


@dataclass(frozen=True)
class MilestoneEntry:
    """One milestone from the §26.1 gate order, with its requirement allocation."""

    milestone_id: str
    name: str
    status: MilestoneStatus
    requirements: tuple[str, ...]
    exit_gate: str
    #: Backend test profiles that MUST have been enabled in the run validating this
    #: milestone, e.g. ``("postgres",)``. Without this, a milestone whose schema conformance
    #: needs PostgreSQL could be signed off by a run in which every PostgreSQL test was
    #: skipped -- which is how "deselected" quietly becomes "covered".
    gate_profile: tuple[str, ...] = ()

    @property
    def is_complete(self) -> bool:
        return self.status == "DONE"


@dataclass(frozen=True)
class MilestoneCatalog:
    path: Path
    schema_version: int
    milestones: tuple[MilestoneEntry, ...]

    def get(self, milestone_id: str) -> MilestoneEntry:
        for milestone in self.milestones:
            if milestone.milestone_id == milestone_id:
                return milestone
        raise KeyError(milestone_id)

    @property
    def allocated_requirements(self) -> tuple[str, ...]:
        return tuple(
            requirement for milestone in self.milestones for requirement in milestone.requirements
        )

    def milestone_of(self, requirement_id: str) -> MilestoneEntry | None:
        for milestone in self.milestones:
            if requirement_id in milestone.requirements:
                return milestone
        return None

    def completed_requirements(self) -> frozenset[str]:
        """Requirements whose milestone is DONE, so a real test MUST already exist."""
        return frozenset(
            requirement
            for milestone in self.milestones
            if milestone.is_complete
            for requirement in milestone.requirements
        )


def registry_path() -> Path:
    return repo_root() / "docs" / "normative_statements.yaml"


def milestones_path() -> Path:
    return repo_root() / "docs" / "milestones.yaml"


def spec_issues_dir() -> Path:
    """Where open questions about the specification itself are recorded (AGT-015)."""
    return repo_root() / "docs" / "spec_issues"


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RegistryError(f"file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RegistryError(f"{path.name} must contain a top-level mapping")
    return data


def _require_str(payload: dict[str, Any], field: str, context: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{context}: field {field!r} must be a non-empty string")
    return value.strip()


@lru_cache(maxsize=1)
def load_registry(path: Path | None = None) -> NormativeStatementRegistry:
    resolved = path or registry_path()
    data = _load_yaml_mapping(resolved)

    schema_version = data.get("schema_version")
    if not isinstance(schema_version, int):
        raise RegistryError("normative_statements.yaml: schema_version must be an int")
    spec_version = _require_str(data, "spec_version", "normative_statements.yaml")

    raw_statements = data.get("normative_statements")
    if not isinstance(raw_statements, list) or not raw_statements:
        raise RegistryError(
            "normative_statements.yaml: normative_statements must be a non-empty list"
        )

    statements: list[NormativeStatement] = []
    for index, raw in enumerate(raw_statements):
        if not isinstance(raw, dict):
            raise RegistryError(f"normative_statements[{index}] must be a mapping")
        context = f"normative_statements[{index}]"
        key = _require_str(raw, "key", context)
        level = _require_str(raw, "level", f"{context} ({key})")
        if level not in _VALID_LEVELS:
            raise RegistryError(
                f"{context} ({key}): level {level!r} not in {sorted(_VALID_LEVELS)}"
            )
        raw_tests = raw.get("tests", []) or []
        if not isinstance(raw_tests, list) or any(not isinstance(test, str) for test in raw_tests):
            raise RegistryError(f"{context} ({key}): tests must be a list of strings")
        rationale = raw.get("deferred_rationale")
        if rationale is not None and not isinstance(rationale, str):
            raise RegistryError(f"{context} ({key}): deferred_rationale must be a string")
        review_at = raw.get("review_at")
        if review_at is not None and not isinstance(review_at, str):
            raise RegistryError(f"{context} ({key}): review_at must be a string")
        spec_issue = raw.get("spec_issue")
        if spec_issue is not None and not isinstance(spec_issue, str):
            raise RegistryError(f"{context} ({key}): spec_issue must be a string")
        statements.append(
            NormativeStatement(
                key=key,
                section=_require_str(raw, "section", f"{context} ({key})"),
                level=level,  # type: ignore[arg-type]
                requirement_id=_require_str(raw, "requirement_id", f"{context} ({key})"),
                tests=tuple(test.strip() for test in raw_tests),
                deferred_rationale=" ".join(rationale.split()) if rationale else None,
                review_at=review_at.strip() if review_at else None,
                spec_issue=spec_issue.strip() if spec_issue else None,
            )
        )

    return NormativeStatementRegistry(
        path=resolved,
        schema_version=schema_version,
        spec_version=spec_version,
        statements=tuple(statements),
    )


@lru_cache(maxsize=1)
def load_milestones(path: Path | None = None) -> MilestoneCatalog:
    resolved = path or milestones_path()
    data = _load_yaml_mapping(resolved)

    schema_version = data.get("schema_version")
    if not isinstance(schema_version, int):
        raise RegistryError("milestones.yaml: schema_version must be an int")

    raw_milestones = data.get("milestones")
    if not isinstance(raw_milestones, list) or not raw_milestones:
        raise RegistryError("milestones.yaml: milestones must be a non-empty list")

    milestones: list[MilestoneEntry] = []
    for index, raw in enumerate(raw_milestones):
        if not isinstance(raw, dict):
            raise RegistryError(f"milestones[{index}] must be a mapping")
        context = f"milestones[{index}]"
        milestone_id = _require_str(raw, "id", context)
        status = _require_str(raw, "status", f"{context} ({milestone_id})")
        if status not in _VALID_STATUSES:
            raise RegistryError(
                f"{context} ({milestone_id}): status {status!r} not in {sorted(_VALID_STATUSES)}"
            )
        raw_requirements = raw.get("requirements", []) or []
        if not isinstance(raw_requirements, list) or any(
            not isinstance(item, str) for item in raw_requirements
        ):
            raise RegistryError(
                f"{context} ({milestone_id}): requirements must be a list of strings"
            )
        raw_gate_profile = raw.get("gate_profile", []) or []
        if not isinstance(raw_gate_profile, list) or any(
            not isinstance(item, str) for item in raw_gate_profile
        ):
            raise RegistryError(
                f"{context} ({milestone_id}): gate_profile must be a list of strings"
            )
        unknown_gates = sorted(set(raw_gate_profile) - set(GATE_ENV_VARS))
        if unknown_gates:
            raise RegistryError(
                f"{context} ({milestone_id}): unknown gate_profile entries "
                f"{unknown_gates}; known gates are {sorted(GATE_ENV_VARS)}"
            )
        milestones.append(
            MilestoneEntry(
                milestone_id=milestone_id,
                name=_require_str(raw, "name", f"{context} ({milestone_id})"),
                status=status,  # type: ignore[arg-type]
                requirements=tuple(item.strip() for item in raw_requirements),
                exit_gate=_require_str(raw, "exit_gate", f"{context} ({milestone_id})"),
                gate_profile=tuple(item.strip() for item in raw_gate_profile),
            )
        )

    return MilestoneCatalog(
        path=resolved,
        schema_version=schema_version,
        milestones=tuple(milestones),
    )
