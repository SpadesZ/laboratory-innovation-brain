"""A model server on this machine is not presumed free: the database side of 011v.

Against the real server, as the deployment's roles (the fixtures of
`test_g0_spend_admin_postgres.py`: `app` the services, `owner` a member of
`lab_brain_spend_admin`, `su` the migrator setting the scene):

    wildcard        the Owner cannot declare `*` free; a `*` row left by 011t frees nothing
    evidence        the services may report a declared-free endpoint that answered like a paid
                    proxy; the report withdraws exactly that declaration until the Owner renews it
    append-only     nobody edits or deletes a report, or writes one directly -- not even where
                    table writes were granted by mistake
    names only      a report holds signal names, never a value (a cost, a key, a prompt)
    end to end      a "free" local endpoint that sends a billing header: the call is refused, the
                    declaration withdrawn, and the next call refused unsent
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from psycopg import sql

from lab_brain.llm_runtime import spend
from lab_brain.llm_runtime.provider import OpenAICompatibleClient, ProviderError, ProviderFailure
from lab_brain.llm_runtime.spend import PostgresSpendGuard
from tests.integration import test_g0_spend_admin_postgres as _admin
from tests.integration.test_g0_spend_admin_postgres import Roles
from tests.transport_endpoints import Endpoint

pytestmark = [pytest.mark.postgres, pytest.mark.real_spend_guard]

# The deployment's roles, made and dropped per test exactly as in the 011t tests.
su = _admin.su
roles = _admin.roles

KEY = "sk-test-local-proxy-pg-0123456789abcdefABCDEF"


def _free(c: Any, host: str, model: str) -> bool:
    return bool(c.execute("SELECT llm_spend_endpoint_is_free(%s, %s)", (host, model)).fetchone()[0])


def _declare(roles: Roles, host: str, model: str) -> None:
    with roles.connect(roles.owner) as owner:
        spend.declare_free_endpoint(
            owner, host, model, reason="a model server on this machine", actor_id="act:owner"
        )


def test_the_owner_cannot_declare_every_model_free(su, roles):
    with (
        roles.connect(roles.owner) as owner,
        pytest.raises(psycopg.errors.RaiseException, match="names one model"),
    ):
        spend.declare_free_endpoint(owner, "127.0.0.1:4000", "*", reason="x", actor_id="act:o")


def test_a_wildcard_row_from_before_frees_nothing(su, roles):
    host = "127.0.0.1:40001"
    with su.transaction():  # a row 011t's function could write, planted as its writer did
        su.execute("SELECT set_config('lab_brain.llm_spend_writer', 'on', TRUE)")
        su.execute(
            "INSERT INTO llm_spend_free_endpoints (endpoint_host, model, free, reason, actor_id)"
            " VALUES (%s, '*', TRUE, 'declared before 011v', 'act:owner')",
            (host,),
        )
    for model in ("qwen2.5:7b", "gpt-4o", "*"):
        assert not _free(su, host, model)


def test_a_report_withdraws_exactly_that_declaration_until_the_owner_renews_it(su, roles):
    host = "127.0.0.1:40002"
    _declare(roles, host, "llama3")
    _declare(roles, host, "qwen2.5:7b")
    assert _free(su, host, "llama3") and _free(su, host, "qwen2.5:7b")
    with roles.connect(roles.app) as app:
        evidence = app.execute(
            "SELECT llm_spend_report_paid_proxy(%s, %s, %s)",
            (host, "llama3", ["header:x-litellm-response-cost"]),
        ).fetchone()[0]
        assert evidence is not None
        assert not _free(app, host, "llama3")
        assert _free(app, host, "qwen2.5:7b"), "another model's declaration stands"
    _declare(roles, host, "llama3")  # the Owner looked, and declares it free again
    assert _free(su, host, "llama3")


def test_a_report_with_nothing_declared_withdraws_nothing(su, roles):
    with roles.connect(roles.app) as app:
        got = app.execute(
            "SELECT llm_spend_report_paid_proxy('127.0.0.1:40003', 'm', ARRAY['usage.cost'])"
        ).fetchone()[0]
    assert got is None
    assert su.execute(
        "SELECT count(*) FROM llm_spend_paid_proxy_evidence WHERE endpoint_host = '127.0.0.1:40003'"
    ).fetchone() == (0,)


@pytest.mark.parametrize(
    "signals",
    [
        ["header:x-litellm-response-cost=0.0042"],
        ["usage.cost 0.1"],
        ["Bearer sk-live-abcdef"],
        [],
        ["header:" + "x" * 200],
    ],
)
def test_a_report_holds_signal_names_never_values(su, roles, signals):
    host = "127.0.0.1:40004"
    _declare(roles, host, "m")
    with roles.connect(roles.app) as app, pytest.raises(psycopg.errors.RaiseException):
        app.execute("SELECT llm_spend_report_paid_proxy(%s, 'm', %s)", (host, signals))
    assert _free(su, host, "m")


def test_nobody_edits_deletes_or_writes_a_report_directly(su, roles):
    host = "127.0.0.1:40005"
    _declare(roles, host, "m")
    with roles.connect(roles.app) as app:
        app.execute("SELECT llm_spend_report_paid_proxy(%s, 'm', ARRAY['usage.cost'])", (host,))
    for statement in (
        "UPDATE llm_spend_paid_proxy_evidence SET signals = ARRAY['usage.x'] WHERE endpoint_host"
        " = %s",
        "DELETE FROM llm_spend_paid_proxy_evidence WHERE endpoint_host = %s",
    ):
        with roles.connect(roles.app) as app, pytest.raises(psycopg.errors.InsufficientPrivilege):
            app.execute(statement, (host,))
        # The migrator is stopped by the trigger.
        with (
            pytest.raises(psycopg.errors.RaiseException, match="never edited or deleted"),
            su.transaction(),
        ):
            su.execute(statement, (host,))
    assert not _free(su, host, "m")


def test_the_trigger_holds_where_writes_were_granted_by_mistake(su, roles):
    host = "127.0.0.1:40006"
    _declare(roles, host, "m")
    with roles.connect(roles.app) as app:
        app.execute("SELECT llm_spend_report_paid_proxy(%s, 'm', ARRAY['usage.cost'])", (host,))
    su.execute(
        sql.SQL(
            "GRANT INSERT, UPDATE, DELETE ON llm_spend_paid_proxy_evidence TO {};"
            "GRANT USAGE ON SEQUENCE llm_spend_paid_proxy_evidence_evidence_id_seq TO {}"
        ).format(sql.Identifier(roles.app), sql.Identifier(roles.app))
    )
    try:
        with roles.connect(roles.app) as app:
            for statement in (
                "DELETE FROM llm_spend_paid_proxy_evidence WHERE endpoint_host = %s",
                "UPDATE llm_spend_paid_proxy_evidence SET declaration_id = 1 WHERE endpoint_host"
                " = %s",
            ):
                with pytest.raises(psycopg.errors.RaiseException, match="never edited"):
                    app.execute(statement, (host,))
            with (
                pytest.raises(psycopg.errors.RaiseException, match="written only by"),
                app.transaction(),
            ):
                app.execute("SELECT set_config('lab_brain.llm_spend_writer', 'on', TRUE)")
                app.execute(
                    "INSERT INTO llm_spend_paid_proxy_evidence (declaration_id,"
                    " endpoint_host, model, signals) SELECT declaration_id, endpoint_host,"
                    " model, ARRAY['usage.cost'] FROM llm_spend_free_endpoints"
                    " WHERE endpoint_host = %s",
                    (host,),
                )
    finally:
        su.execute(
            sql.SQL(
                "REVOKE INSERT, UPDATE, DELETE ON llm_spend_paid_proxy_evidence FROM {};"
                "REVOKE USAGE ON SEQUENCE llm_spend_paid_proxy_evidence_evidence_id_seq FROM {}"
            ).format(sql.Identifier(roles.app), sql.Identifier(roles.app))
        )
    assert not _free(su, host, "m")


def test_the_services_cannot_renew_a_withdrawn_declaration(su, roles):
    host = "127.0.0.1:40007"
    _declare(roles, host, "m")
    with roles.connect(roles.app) as app:
        app.execute("SELECT llm_spend_report_paid_proxy(%s, 'm', ARRAY['usage.cost'])", (host,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            spend.declare_free_endpoint(app, host, "m", reason="renew", actor_id="act:app")
    assert not _free(su, host, "m")


def test_a_free_local_endpoint_that_bills_is_refused_and_stays_refused(su, roles, monkeypatch):
    for name in ("LAB_BRAIN_LLM_SPEND_BUDGET", "LAB_BRAIN_LLM_SPEND_DSN"):
        monkeypatch.delenv(name, raising=False)
    spend.install(None)
    endpoint = Endpoint(headers={"x-litellm-response-cost": "0.0042"}).start()
    try:
        host = f"127.0.0.1:{endpoint.port}"
        _declare(roles, host, "m")
        guard = PostgresSpendGuard(roles.dsn(roles.app), None)  # the services' guard, no budget
        client = OpenAICompatibleClient(endpoint.origin + "/v1", KEY, spend=guard)
        with pytest.raises(ProviderError) as refused:
            client.chat("m", "a prompt the proxy forwarded to a paid provider")
        assert refused.value.failure is ProviderFailure.SPEND_REFUSED
        assert "withdrawn" in refused.value.detail
        assert not _free(su, host, "m")
        row = su.execute(
            "SELECT signals, db_role FROM llm_spend_paid_proxy_evidence WHERE endpoint_host = %s",
            (host,),
        ).fetchone()
        assert row == (["header:x-litellm-response-cost"], roles.app)
        sent = len(endpoint.seen)
        with pytest.raises(ProviderError) as again:
            client.chat("m", "no longer free, and no budget")
        assert again.value.failure is ProviderFailure.SPEND_REFUSED
        assert len(endpoint.seen) == sent, "refused unsent"
    finally:
        endpoint.stop()
