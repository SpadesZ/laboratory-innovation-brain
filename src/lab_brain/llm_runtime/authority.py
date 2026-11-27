"""Who configures the deployment's language-model routes, and whose evidence may use them (`012f`).

TWO AUTHORITIES, NEVER ONE.

    deployment LLM administration   configuring connections, models, locks, runtimes and bindings.
                                    Held by an actor the deployment's operator granted it to
                                    (`llm_administrators`). Project membership grants none of it.
    project egress authorization    whether THIS project's evidence may reach an EXTERNAL model
                                    route, which routes, under which labels. Declared by the
                                    project itself (`project_llm_egress_policies`): an active member
                                    of that project holding the `LLM_EGRESS` approval scope, for
                                    labels that member is cleared for, never in Private Mode.

A global runtime supplies ROUTES. It never supplies PERMISSION: the egress gate consults, for each
call, the policy of the project the evidence belongs to -- that project's own declaration, in that
project's own privacy mode, narrowed to the routes the active runtime actually serves and to the
labels the runtime's administrator allowed any project to send. A project that declared nothing has
no policy, and the gate refuses every external call it would make.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lab_brain.core.models.enums import SensitivityLabel
from lab_brain.core.models.identifiers import new_id
from lab_brain.security.egress import LLM_EGRESS_SCOPE, EgressPolicy, PrivacyMode


class AuthorityRefused(ValueError):
    """The database refused the declaration; the message is its rule."""


def is_administrator(connection: Any, actor_id: str) -> bool:
    """Whether `actor_id` currently holds deployment LLM administration (`012f`)."""
    row = connection.execute("SELECT llm_is_administrator(%s)", (actor_id,)).fetchone()
    return bool(row is not None and row[0])


@dataclass(frozen=True)
class ProjectEgress:
    """One version of a project's own external-model egress declaration."""

    policy_id: str
    project_id: str
    version: int
    connection_ids: tuple[str, ...]
    labels: tuple[str, ...]
    declared_by: str
    declared_at: dt.datetime

    @property
    def withdrawn(self) -> bool:
        return not self.connection_ids


_POLICY = (
    "policy_id, project_id, version, approved_connection_ids, permitted_labels, "
    "declared_by_actor_id, declared_at"
)


class ProjectEgressPolicies:
    def __init__(self, connection: Any, *, mint: Callable[[str], str] = new_id) -> None:
        self._c = connection
        self._mint = mint

    def current(self, project_id: str) -> ProjectEgress | None:
        row = self._c.execute(
            f"SELECT {_POLICY} FROM project_llm_egress_policies WHERE project_id = %s"
            " ORDER BY version DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        return None if row is None else _policy(row)

    def history(self, project_id: str) -> list[ProjectEgress]:
        rows = self._c.execute(
            f"SELECT {_POLICY} FROM project_llm_egress_policies WHERE project_id = %s"
            " ORDER BY version DESC",
            (project_id,),
        ).fetchall()
        return [_policy(r) for r in rows]

    def privacy_mode(self, project_id: str) -> str | None:
        row = self._c.execute(
            "SELECT privacy_mode FROM projects WHERE project_id = %s AND archived_at IS NULL",
            (project_id,),
        ).fetchone()
        return None if row is None else str(row[0])

    def declare(
        self,
        project_id: str,
        *,
        actor_id: str,
        connection_ids: Iterable[str],
        labels: Iterable[str],
        at: dt.datetime,
    ) -> ProjectEgress:
        """A new version of the project's declaration. The database decides whether `actor_id`
        may make it; an empty connection list withdraws every approval."""
        connections = sorted(set(connection_ids))
        permitted = sorted(set(labels)) if connections else []
        current = self.current(project_id)
        policy_id = self._mint("llm_egress_policy")
        try:
            with self._c.transaction():
                self._c.execute(
                    f"INSERT INTO project_llm_egress_policies ({_POLICY})"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        policy_id,
                        project_id,
                        (current.version if current is not None else 0) + 1,
                        connections,
                        permitted,
                        actor_id,
                        at,
                    ),
                )
        except Exception as exc:  # the database's own rule, surfaced as it said it
            diag = getattr(exc, "diag", None)
            if getattr(exc, "sqlstate", None) is None and diag is None:
                raise
            message = getattr(diag, "message_primary", None) or str(exc).splitlines()[0]
            raise AuthorityRefused(message) from exc
        declared = self.current(project_id)
        assert declared is not None and declared.policy_id == policy_id
        return declared

    def effective(
        self,
        project_id: str,
        *,
        routes: Mapping[str, str],
        ceiling: frozenset[SensitivityLabel],
    ) -> EgressPolicy | None:
        """The policy the egress gate applies to `project_id`'s evidence now.

        `routes` maps each EXTERNAL connection the active runtime serves (id -> the provider name
        its `ModelSlot` records); `ceiling` is what the runtime allows any project to send. The
        project's declaration is narrowed to both, and its privacy mode is its own. `None` -- the
        gate's "no declared egress policy" -- when the project declared nothing, or is unknown or
        archived.
        """
        mode = self.privacy_mode(project_id)
        declared = self.current(project_id)
        if mode is None or declared is None:
            return None
        return EgressPolicy(
            policy_id=declared.policy_id,
            version=str(declared.version),
            project_id=project_id,
            mode=PrivacyMode(mode),
            declared_by_actor_id=declared.declared_by,
            permitted_labels=frozenset(SensitivityLabel(x) for x in declared.labels) & ceiling,
            approved_providers=frozenset(routes[c] for c in declared.connection_ids if c in routes),
        )

    def statement(
        self,
        project_id: str,
        *,
        routes: Mapping[str, str],
        ceiling: frozenset[SensitivityLabel],
    ) -> str:
        """How the report states the egress this project's run was held to."""
        if not routes:
            return (
                f"Project egress ({project_id}): every bound model is LOCAL, so no model call "
                "leaves this machine and no project egress authorization is involved."
            )
        policy = self.effective(project_id, routes=routes, ceiling=ceiling)
        if policy is None:
            return (
                f"Project egress ({project_id}): this project has declared no external-model "
                f"egress policy, so none of its evidence may reach the external routes "
                f"({', '.join(sorted(routes.values()))}); every such call is refused by the egress "
                "gate and recorded. A global runtime supplies routes, not permission."
            )
        if policy.mode is PrivacyMode.PRIVATE:
            return (
                f"Project egress ({project_id}): the project is in Private Mode, so none of its "
                "evidence leaves this machine (§14.2), whatever its policy lists."
            )
        providers = ", ".join(sorted(policy.approved_providers)) or "none of the active routes"
        labels = ", ".join(sorted(x.value for x in policy.permitted_labels)) or "no label"
        return (
            f"Project egress ({project_id}): policy `{policy.policy_id}` version {policy.version}, "
            f"declared by `{policy.declared_by_actor_id}` for this project ({policy.mode.value} "
            f"mode): evidence classified {labels} may reach {providers}. Anything else is refused "
            "by the egress gate and recorded; RESTRICTED_NDA never leaves; the researcher's own "
            "clearance also applies."
        )


def _policy(row: Sequence[Any]) -> ProjectEgress:
    return ProjectEgress(
        policy_id=str(row[0]),
        project_id=str(row[1]),
        version=int(row[2]),
        connection_ids=tuple(row[3] or ()),
        labels=tuple(row[4] or ()),
        declared_by=str(row[5]),
        declared_at=row[6],
    )


__all__ = [
    "LLM_EGRESS_SCOPE",
    "AuthorityRefused",
    "ProjectEgress",
    "ProjectEgressPolicies",
    "is_administrator",
]
