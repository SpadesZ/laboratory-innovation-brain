"""Research data: files a researcher adds to a project, before and apart from any research run.

    add research data -> ingestion, status, review -> choose available data -> start research

ONE PATH IN. A file added here goes through exactly what every ingestion goes through
(`composition.IngestionService`): a Job with no episode (M1 admits ingestion outside one), the
secret scan, the Artifact and its ArtifactOccurrence under the sensitivity label the researcher
declared, segmentation into EvidenceUnits, and the ingestion item whose state `derive_state` reads.
Content identity is the pipeline's: the same bytes added again are the SAME artifact, and the later
item is derived DUPLICATE -- nothing is copied, and a duplicate adds no evidence. The one thing that
had nowhere to live is what the researcher DECLARED the material to be (§6.5: declared, never
inferred), recorded per item (`012g`) -- the kind and the label, both as declared.

AUTHORIZATION BEFORE ANY WRITE. `add` refuses, before a job, a byte or a row exists: an actor the
read gate does not admit to the project, a kind that is not research material, and a label the
actor is not cleared for in that project. The last is the web intake's own rule: a file stored under
a label its uploader cannot read would be data they can neither see nor select.

A DUPLICATE DECLARES NOTHING. Its bytes are an artifact the project already holds, under the label
and the kind its first arrival was declared with; the later upload's declaration is kept (it is
what was said) and shown beside the one in force, but it changes neither. The label in force is the
occurrence's -- the first arrival's -- exactly as the pipeline stores it.

ONE PATH OUT. Nothing here admits evidence. A research run that uses an item passes its artifact to
`ResearchEpisodeService` (`ProjectData`), which authorizes it and admits its existing units through
the same `StatementAdmitter` it uses for a file uploaded with the run -- no second ingestion, no
copied unit.

WHO SEES WHAT. Every read is the inbox's: an actor the read gate admits to the project sees its
items' names and derived states -- no evidence body. Another project's items are never listed, an
artifact not present in the project is never offered, and an artifact the actor's clearance does not
cover is listed but never offered for research.
"""

from __future__ import annotations

import datetime as dt
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote

from lab_brain.composition import IngestionService
from lab_brain.core.models.access import ProjectMembership
from lab_brain.core.models.base import utc_now
from lab_brain.core.models.enums import SensitivityLabel, TrustClass
from lab_brain.core.models.identifiers import new_id
from lab_brain.surface.ingestion_item import ItemState, derive_state

#: What a researcher may declare a file to be, and the trust class it is declared as (§6.5). The
#: same three a research run's uploads are declared as (`interfaces.cli._DOCUMENT_KINDS`).
MATERIAL_KINDS: Mapping[str, TrustClass] = {
    "measurement": TrustClass.INTERNAL_MEASUREMENT,
    "run_record": TrustClass.INTERNAL_RUN,
    "note": TrustClass.EXPERT_HEURISTIC,
}

#: States in which an item's evidence can be used by a research run: all of it, or the part the
#: ingestion produced (PARTIAL says what was lost).
USABLE_STATES: frozenset[ItemState] = frozenset({ItemState.READY, ItemState.PARTIAL})


class LabelNotCleared(ValueError):
    """The declared label is not one the actor may read in the project. Nothing was written."""

    def __init__(self, label: SensitivityLabel, held: frozenset[SensitivityLabel]) -> None:
        self.label = label
        self.held = held
        super().__init__(
            f"not cleared for {label.value} in this project "
            f"(holds: {', '.join(sorted(x.value for x in held)) or 'none'})"
        )


@dataclass(frozen=True)
class NewFile:
    name: str
    data: bytes
    media_type: str


@dataclass(frozen=True)
class DataItem:
    """One ingestion item of the project, as a researcher reads it."""

    item_id: str
    name: str
    state: ItemState
    submitted_at: dt.datetime
    artifact_id: str | None
    #: The trust class declared for it, if it was added as research data (`012g`).
    declared_kind: TrustClass | None
    #: The label the researcher declared for THIS upload, if it was added as research data.
    declared_label: str | None
    #: The label in force: the project's occurrence of the artifact, if it was stored.
    sensitivity: str | None
    evidence_units: int
    #: RESEARCH_DATA (added here), RESEARCH_RUN (uploaded with a run) or OTHER.
    origin: str
    episode_id: str | None
    #: The earlier item holding the same artifact, for a DUPLICATE.
    duplicate_of: str | None
    error_ids: tuple[str, ...]
    #: Whether this actor's clearance covers the label in force (False when nothing was stored).
    readable: bool


@dataclass(frozen=True)
class UsableData:
    """One artifact of the project a research run may use: its first item, as ingested."""

    artifact_id: str
    item_id: str
    name: str
    state: ItemState
    #: The kind its first arrival was declared as -- never a later duplicate's.
    declared_kind: TrustClass | None
    sensitivity: str | None
    evidence_units: int
    submitted_at: dt.datetime


class ResearchData:
    def __init__(
        self,
        *,
        connection: Any,
        artifact_store: Any,
        clock: Callable[[], dt.datetime] = utc_now,
    ) -> None:
        self._c = connection
        self._clock = clock
        self._service = IngestionService(
            connection=connection, artifact_store=artifact_store, clock=clock
        )

    def clearance(self, *, project_id: str, actor_id: str) -> frozenset[SensitivityLabel]:
        """The labels `actor_id` may read in `project_id` now (none without an active
        membership). `ProjectMembership.clears` is the one rule; this only reads its record."""
        row = self._c.execute(
            "SELECT actor_id, project_id, role, sensitivity_clearance, approval_scopes, active"
            " FROM project_memberships WHERE actor_id = %s AND project_id = %s",
            (actor_id, project_id),
        ).fetchone()
        if row is None or not row[5]:
            return frozenset()
        membership = ProjectMembership.model_validate(
            {
                "actor_id": row[0],
                "project_id": row[1],
                "role": row[2],
                "sensitivity_clearance": tuple(row[3] or ()),
                "approval_scopes": tuple(row[4] or ()),
                "active": row[5],
            }
        )
        return frozenset(label for label in SensitivityLabel if membership.clears(label))

    def add(
        self,
        *,
        project_id: str,
        actor_id: str,
        files: Sequence[NewFile],
        kind: TrustClass,
        sensitivity: SensitivityLabel,
    ) -> list[str]:
        """Ingest each file into the project as declared. Returns the ingestion item ids.

        The declaration is the researcher's, both of it: `kind` and `sensitivity` are parameters
        with no default, and nothing here reads a file to guess either.
        """
        # Authorization first and fatal, as a research run's: nothing is written for a
        # non-member, for a kind that is not research material, or under a label the actor could
        # not read back.
        self._service.read_gate().require_project(actor_id=actor_id, project_id=project_id)
        if kind not in MATERIAL_KINDS.values():
            raise ValueError(f"{kind.value} is not a kind of research material a researcher adds")
        held = self.clearance(project_id=project_id, actor_id=actor_id)
        if sensitivity not in held:
            raise LabelNotCleared(sensitivity, held)
        items: list[str] = []
        for file in files:
            job = self._service.submit(
                project_id=project_id,
                actor_id=actor_id,
                # One upload, one job: adding the same file again is a second arrival, which the
                # pipeline's content identity makes the same artifact and a DUPLICATE item.
                idempotency_key=f"research-data:{secrets.token_hex(16)}",
                trace_id=new_id("trace"),
            )
            result = self._service.ingest(
                file.data,
                job_id=job.job_id,
                actor_id=actor_id,
                sensitivity_label=sensitivity,
                uri=f"workspace-upload:{quote(file.name or 'unnamed')}",
                media_type=file.media_type,
            )
            item_id = result.outcome.item_id
            self._c.execute(
                "INSERT INTO research_data_declarations (item_id, project_id, actor_id,"
                " declared_kind, declared_label, file_name, declared_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    item_id,
                    project_id,
                    actor_id,
                    kind.value,
                    sensitivity.value,
                    (file.name or "unnamed")[:255],
                    self._clock(),
                ),
            )
            items.append(item_id)
        return items

    def items(self, *, project_id: str, actor_id: str) -> list[DataItem]:
        """Every ingestion item of the project, newest first. Raises `ScientificReadRefused` for
        an actor the gate does not admit, as the inbox does."""
        view = self._service.inbox(actor_id=actor_id, project_id=project_id)
        gate = self._service.read_gate()
        declared = {
            str(r[0]): (TrustClass(r[1]), str(r[2]), str(r[3]))
            for r in self._c.execute(
                "SELECT item_id, declared_kind, declared_label, file_name"
                " FROM research_data_declarations WHERE project_id = %s",
                (project_id,),
            ).fetchall()
        }
        artifacts = sorted({i.raw_artifact_id for i in view.items if i.raw_artifact_id})
        labels = dict(
            self._c.execute(
                "SELECT artifact_id, sensitivity_label FROM artifact_occurrences"
                " WHERE project_id = %s AND artifact_id = ANY(%s)",
                (project_id, artifacts),
            ).fetchall()
        )
        units = dict(
            self._c.execute(
                "SELECT artifact_id, count(*) FROM evidence_unit_occurrences"
                " WHERE project_id = %s AND artifact_id = ANY(%s) GROUP BY artifact_id",
                (project_id, artifacts),
            ).fetchall()
        )
        readable = {
            a: gate.authorize_artifact(
                actor_id=actor_id, project_id=project_id, artifact_id=a
            ).allowed
            for a in artifacts
        }
        first_holder: dict[str, str] = {}
        for item in sorted(view.items, key=lambda i: (i.submitted_at, i.item_id)):
            if item.raw_artifact_id and item.raw_artifact_id not in first_holder:
                first_holder[item.raw_artifact_id] = item.item_id
        out: list[DataItem] = []
        for item in view.items:
            jobs = view.jobs_for(item.item_id)
            episode = next((j.episode_id for j in jobs if j.episode_id), None)
            kind, label, file_name = declared.get(item.item_id, (None, None, None))
            artifact = item.raw_artifact_id
            holder = first_holder.get(artifact or "")
            out.append(
                DataItem(
                    item_id=item.item_id,
                    name=file_name or _upload_name(item.display_name),
                    state=derive_state(
                        item,
                        jobs=jobs,
                        open_review_ids=view.open_review_ids,
                        blocking_conflict_ids=view.blocking_conflict_ids,
                    ),
                    submitted_at=item.submitted_at,
                    artifact_id=artifact,
                    declared_kind=kind,
                    declared_label=label,
                    sensitivity=labels.get(artifact) if artifact else None,
                    evidence_units=int(units.get(artifact, 0)) if artifact else 0,
                    origin=(
                        "RESEARCH_DATA"
                        if item.item_id in declared
                        else ("RESEARCH_RUN" if episode else "OTHER")
                    ),
                    episode_id=episode,
                    duplicate_of=holder
                    if item.duplicate_of_artifact_id and holder and holder != item.item_id
                    else None,
                    error_ids=tuple(item.error_ids),
                    readable=bool(artifact and readable.get(artifact)),
                )
            )
        return sorted(out, key=lambda d: (d.submitted_at, d.item_id), reverse=True)

    def usable(self, *, project_id: str, actor_id: str) -> list[UsableData]:
        """The project's artifacts a research run may use now: one per artifact, its first item,
        in a usable state, with evidence units, under a label this actor may read. Its kind is
        the one that first item was declared with; a later duplicate re-declares nothing, and with
        no declaration the researcher chooses one when selecting it."""
        usable: dict[str, UsableData] = {}
        for item in sorted(
            self.items(project_id=project_id, actor_id=actor_id),
            key=lambda d: (d.submitted_at, d.item_id),
        ):
            if (
                item.artifact_id is None
                or item.artifact_id in usable
                or item.duplicate_of is not None
                or item.state not in USABLE_STATES
                or item.evidence_units == 0
                or not item.readable
            ):
                continue
            usable[item.artifact_id] = UsableData(
                artifact_id=item.artifact_id,
                item_id=item.item_id,
                name=item.name,
                state=item.state,
                declared_kind=item.declared_kind,
                sensitivity=item.sensitivity,
                evidence_units=item.evidence_units,
                submitted_at=item.submitted_at,
            )
        return sorted(usable.values(), key=lambda u: (u.submitted_at, u.item_id), reverse=True)

    def explain(self, error_id: str, *, project_id: str, actor_id: str) -> tuple[str, str]:
        """The M1 message catalog's reason code and summary for an item's error, authorized as
        the CLI's `explain` is. Never technical detail."""
        payload = self._service.diagnostics().default_payload(
            error_id, actor_id=actor_id, project_id=project_id
        )
        message = payload.message
        return message.reason_code, message.summary


def _upload_name(display_name: str) -> str:
    """The file name inside a workspace upload URI, for display."""
    return unquote(display_name.removeprefix("workspace-upload:")) or display_name


__all__ = [
    "MATERIAL_KINDS",
    "USABLE_STATES",
    "DataItem",
    "LabelNotCleared",
    "NewFile",
    "ResearchData",
    "UsableData",
]
