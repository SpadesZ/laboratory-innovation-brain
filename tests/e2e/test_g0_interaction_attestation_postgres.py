"""G0-A, strengthened: a session audit reference alone does not prove an authenticated interaction.

THE GAP (Independent Chief Auditor, 2026-10-28). `011n` checks that a WEB_SESSION run names a
live session of its own actor, who is an active, cleared member of the project. But session audit
references are not secret -- they are readable from `account_sessions` and printed in reports --
so any database writer holding the application role's privileges can insert a WEB_SESSION run
naming another live session's reference, for that session's own actor and project, at a valid
time. `011n` accepts it, and before `011q` the report and page rendered it as a "signed-in web
session" run. `test_a_forged_run_naming_a_real_session_is_never_shown_as_authenticated` is the
demonstration.

THE CLOSURE (`011q`, `security.interaction_attestation`). On an authenticated, CSRF-verified web
request that starts or continues a run, the web tier signs a canonical statement binding the run,
episode, trace, actor, project, session reference, route, method and nonce with an Ed25519 key it
alone holds; the public keys are pinned OUTSIDE the database. A database writer can write rows
but cannot make one verify. Only INTERACTION_VERIFIED is described as an authenticated
interaction; every other level says what is not proven. A12 (a database writer with migration
rights) is unchanged and remains the Owner's decision.
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import psycopg
import pytest

from lab_brain.accounts.passwords import token_hash
from lab_brain.interfaces.config import Settings
from lab_brain.interfaces.web import Workspace, allowed_hosts, pages
from lab_brain.interfaces.web.app import LOCALE_COOKIE, SESSION_COOKIE, AccountsConfig
from lab_brain.interfaces.web.i18n import Messages
from lab_brain.research.render import render_markdown
from lab_brain.research.report import SessionProvenance
from lab_brain.research.report_store import report_from_json
from lab_brain.research.vertical import load_vertical_factory
from lab_brain.security.reviewer_identity import SigningKey
from tests.account_fixtures import BASE_URL, CHEAP, PASSWORD, Lab
from tests.e2e.test_g0_session_provenance_postgres import (
    _csrf,
    _episode,
    _project,
    _session_ref,
    _start,
    _tables_holding,
)
from tests.postgres_fixtures import database_url
from tests.report_samples import full_report
from tests.wsgi_client import Browser

pytestmark = pytest.mark.postgres

KEY_ENV = "LAB_BRAIN_INTERACTION_SIGNING_KEY"
AUTH_ENV = "LAB_BRAIN_INTERACTION_AUTHORITIES"


@pytest.fixture
def lab(db: Any) -> Lab:
    return Lab(db)


@pytest.fixture
def keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A web tier's signing key on disk, and its public key pinned in an authorities file."""
    key = SigningKey.generate()
    key_path = tmp_path / "interaction.pem"
    key.save(key_path)
    authorities = tmp_path / "interaction-authorities"
    authorities.write_text(f"web:primary ed25519:{key.public_key}\n", encoding="utf-8")
    monkeypatch.setenv(KEY_ENV, str(key_path))
    monkeypatch.setenv(AUTH_ENV, str(authorities))
    return {"key": key, "key_path": key_path, "authorities": authorities}


def _browser(tmp_path: Path, lab: Lab) -> Browser:
    return Browser(
        Workspace(
            settings=Settings(dsn=database_url()),
            connect=lambda s: psycopg.connect(s.dsn),
            artifact_root=tmp_path / "artifacts",
            vertical_factory=load_vertical_factory("silicon_photonics"),
            allowed_hosts=allowed_hosts("127.0.0.1", 8765),
            accounts=AccountsConfig(mailer=lab.mail, base_url=BASE_URL, cost=CHEAP),
        )
    )


def _signed_in(tmp_path: Path, lab: Lab, email: str) -> Browser:
    browser = _browser(tmp_path, lab)
    page = browser.get("/login")
    reply = browser.post(
        "/login", {"csrf": _csrf(page), "email": email, "password": PASSWORD, "next": "/"}
    )
    assert reply.status == 303, reply.text[:300]
    return browser


@pytest.fixture
def world(lab: Lab, tmp_path: Path) -> dict[str, Any]:
    admin = lab.admin()
    ada = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    admin_browser = _signed_in(tmp_path, lab, "owner@lab.example")
    return {
        "admin": admin,
        "ada": ada,
        "admin_browser": admin_browser,
        "ada_project": _project(admin_browser, "ada@uni.example.edu"),
    }


def _forge(db: Any, run_id: str, episode: str, project: str, actor: str, ref: str) -> None:
    """What a database writer with the application role's privileges can do: a WEB_SESSION row
    naming a real, readable session reference of that actor, in a project they belong to."""
    db.execute(
        "INSERT INTO research_runs (research_run_id, episode_id, project_id, actor_id, ordinal,"
        " started_at, question_label, run_origin, session_audit_ref)"
        " VALUES (%s, %s, %s, %s, 1, now(), 'INTERNAL', 'WEB_SESSION', %s)",
        (run_id, episode, project, actor, ref),
    )


def _forged_report(run_id: str, episode: str, project: str, actor: str, ref: str) -> Any:
    return dataclasses.replace(
        full_report(),
        episode_id=episode,
        project_id=project,
        actor_id=actor,
        trace_id=f"trc:{episode}",
        session_provenance=SessionProvenance(
            origin="WEB_SESSION",
            session_audit_ref=ref,
            actor_id=actor,
            project_id=project,
            research_run_id=run_id,
            trace_id=f"trc:{episode}",
        ),
    )


def _md(report: Any, locale: str) -> str:
    from tests.unit.test_g0_bilingual_export_markdown import CANONICAL, _terms

    return pages.markdown_export(report, (), terms=_terms(locale), canonical_digest=CANONICAL)


def test_a_forged_run_naming_a_real_session_is_never_shown_as_authenticated(
    lab, world, tmp_path, db, keys
):
    """THE GAP. Accepted by `011n` (a readable reference, its own actor, a valid time); it must
    never be rendered as an authenticated interaction, in either language."""
    ada_id, project = world["ada"].actor_id, world["ada_project"]
    ref = _session_ref(db, _signed_in(tmp_path, lab, "ada@uni.example.edu"))
    episode = _episode(db, project, "epi:forged")
    _forge(db, "rrn:forged", episode, project, ada_id, ref)  # `011n` accepts it
    report = _forged_report("rrn:forged", episode, project, ada_id, ref)

    from lab_brain.security.interaction_attestation import ClaimLevel, interaction_claim

    assert interaction_claim(report).level is ClaimLevel.SESSION_RECORDED_UNVERIFIED
    en, zh = render_markdown(report), _md(report, "zh-TW")
    assert "SESSION_RECORDED_UNVERIFIED" in en and "SESSION_RECORDED_UNVERIFIED" in zh
    assert "INTERACTION_VERIFIED" not in en + zh
    assert "originated from an authenticated interaction" not in en.replace(
        "does not show that it originated from an authenticated interaction", ""
    )
    verified_zh = Messages("zh-TW")("md.session.says.INTERACTION_VERIFIED").removeprefix("- ")
    assert verified_zh not in zh
    for locale in ("en", "zh-TW"):
        page = _page(report, locale)
        assert "SESSION_RECORDED_UNVERIFIED" in page and "INTERACTION_VERIFIED" not in page
    # The audit trail, verified in Python against the pinned keys, says the same.
    from lab_brain.security.interaction_attestation import InteractionTrust, audit_claims

    claims = audit_claims(db, InteractionTrust.from_environment())
    assert claims["rrn:forged"].level is ClaimLevel.SESSION_RECORDED_UNVERIFIED


def _page(report: Any, locale: str) -> str:
    from tests.unit.test_g0_bilingual_export_markdown import _terms

    return pages.episode_page(
        actor_id=report.actor_id,
        episode=pages.EpisodeRow(
            report.episode_id,
            report.project_id,
            report.trace_id,
            "Why?",
            "SUSPENDED",
            None,
            None,
            report.started_at,
            None,
            1,
        ),
        runs=[],
        report=report,
        report_ordinal=1,
        csrf="tok",
        continuable=False,
        chrome=pages.Chrome(report.actor_id, locale),
        terms=_terms(locale),
    ).decode()


# -- the real web flow ------------------------------------------------------------------------------


def _run_row(db: Any, episode: str, ordinal: int) -> tuple[Any, ...]:
    return db.execute(
        "SELECT research_run_id, session_audit_ref, interaction_statement, interaction_signature,"
        " interaction_key_id FROM research_runs WHERE episode_id = %s AND ordinal = %s",
        (episode, ordinal),
    ).fetchone()


def test_a_signed_in_csrf_verified_web_run_is_a_verified_interaction(
    lab, world, tmp_path, db, keys
):
    from lab_brain.security.interaction_attestation import (
        ClaimLevel,
        InteractionStatement,
        InteractionTrust,
        audit_claims,
        interaction_claim,
        interaction_key_id,
    )

    ada = _signed_in(tmp_path, lab, "ada@uni.example.edu")
    token = ada.cookies[SESSION_COOKIE]
    started = _start(ada, tmp_path, world["ada_project"])
    assert started.status == 303, started.text[:1000]
    episode = unquote(started.location.split("/episodes/", 1)[1])
    run_id, ref, text, _signature, kid = _run_row(db, episode, 1)
    assert kid == interaction_key_id(keys["key"].public_key)
    statement = InteractionStatement.parse(text)
    (trace,) = db.execute(
        "SELECT trace_id FROM research_episodes WHERE episode_id = %s", (episode,)
    ).fetchone()
    assert (statement.research_run_id, statement.episode_id, statement.trace_id) == (
        run_id,
        episode,
        trace,
    )
    assert (statement.actor_id, statement.project_id, statement.session_audit_ref) == (
        world["ada"].actor_id,
        world["ada_project"],
        ref,
    )
    assert (statement.method, statement.route, statement.csrf_verified) == ("POST", "/runs", True)

    trust = InteractionTrust.from_environment()
    assert audit_claims(db, trust)[run_id].level is ClaimLevel.INTERACTION_VERIFIED
    (ceiling,) = db.execute(
        "SELECT database_claim_ceiling FROM research_run_session_audit WHERE research_run_id = %s",
        (run_id,),
    ).fetchone()
    assert ceiling == "SESSION_RECORDED_UNVERIFIED"  # the database alone never says more
    (stored,) = db.execute(
        "SELECT report FROM research_run_reports WHERE research_run_id = %s", (run_id,)
    ).fetchone()
    report = report_from_json(stored if isinstance(stored, dict) else json.loads(stored))
    assert interaction_claim(report, trust).level is ClaimLevel.INTERACTION_VERIFIED
    # Without the pinned key, the very same record reads unverified (fail closed for the claim).
    assert interaction_claim(report, InteractionTrust()).level is (
        ClaimLevel.SESSION_RECORDED_UNVERIFIED
    )

    # Shown, in both languages, as verified -- and the export pages say so.
    for locale in ("en", "zh-TW"):
        ada.cookies[LOCALE_COOKIE] = locale
        page = ada.get(f"/episodes/{episode}")
        assert page.status == 200 and "INTERACTION_VERIFIED" in page.text
        said = Messages(locale)("md.session.says.INTERACTION_VERIFIED").removeprefix("- ")
        assert said in page.text
    ada.cookies[LOCALE_COOKIE] = "en"
    export = ada.get(f"/episodes/{episode}/runs/1/report.md")
    assert "INTERACTION_VERIFIED" in export.text
    assert "originated from an authenticated interaction" in export.text

    # Continued in another session: its own statement, on the continue route.
    later = _signed_in(tmp_path, lab, "ada@uni.example.edu")
    continued = later.post(f"/episodes/{episode}/continue", {"csrf": _csrf(later.get("/"))})
    assert continued.status == 303, continued.text[:1000]
    run2, ref2, text2, _sig2, _kid2 = _run_row(db, episode, 2)
    second = InteractionStatement.parse(text2)
    assert second.route == f"/episodes/{episode}/continue" and second.research_run_id == run2
    assert second.session_audit_ref == ref2 != ref and second.nonce != statement.nonce
    assert audit_claims(db, trust)[run2].level is ClaimLevel.INTERACTION_VERIFIED

    # No secret anywhere: not the private key, not the session token or its hash.
    pem = keys["key_path"].read_text()
    pem_body = "".join(pem.splitlines()[1:-1])
    for secret in (token, later.cookies[SESSION_COOKIE]):
        assert _tables_holding(db, secret) == set()
        assert _tables_holding(db, token_hash(secret)) == {"account_sessions"}
    assert _tables_holding(db, pem_body) == set()
    shown = [
        later.get(f"/episodes/{episode}"),
        later.get(f"/episodes/{episode}/runs/1/report.md"),
        later.get(f"/episodes/{episode}/runs/2/summary.html"),
    ]
    for page in shown:
        assert page.status == 200
        for secret in (token, token_hash(token), pem_body, later.cookies[SESSION_COOKIE]):
            assert secret not in page.text


def test_without_a_signing_key_web_runs_are_recorded_but_never_verified(
    lab, world, tmp_path, db, monkeypatch
):
    from lab_brain.security.interaction_attestation import (
        ClaimLevel,
        InteractionTrust,
        audit_claims,
    )

    monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.delenv(AUTH_ENV, raising=False)
    ada = _signed_in(tmp_path, lab, "ada@uni.example.edu")
    started = _start(ada, tmp_path, world["ada_project"])
    assert started.status == 303, started.text[:1000]  # the product works
    episode = unquote(started.location.split("/episodes/", 1)[1])
    run_id, ref, text, signature, kid = _run_row(db, episode, 1)
    assert ref is not None and (text, signature, kid) == (None, None, None)
    assert audit_claims(db, InteractionTrust())[run_id].level is (
        ClaimLevel.SESSION_RECORDED_UNVERIFIED
    )
    export = ada.get(f"/episodes/{episode}/runs/1/report.md")
    assert "SESSION_RECORDED_UNVERIFIED" in export.text
    assert "does not show that it originated from an authenticated interaction" in export.text
    assert "INTERACTION_VERIFIED" not in export.text


# -- the database: replay, tampering, immutability -------------------------------------------------


def _signed(key: SigningKey, **fields: Any) -> tuple[str, str]:
    from lab_brain.security.interaction_attestation import InteractionStatement

    statement = InteractionStatement(
        **{
            "route": "/runs",
            "method": "POST",
            "signed_at": dt.datetime.now(dt.UTC),
            "nonce": "ab" * 16,
            **fields,
        }
    )
    text = statement.text()
    return text, key.sign(text.encode())


def _insert_attested(
    db: Any, run_id: str, episode: str, project: str, actor: str, ref: str, att: tuple[str, ...]
) -> None:
    db.execute(
        "INSERT INTO research_runs (research_run_id, episode_id, project_id, actor_id, ordinal,"
        " started_at, question_label, run_origin, session_audit_ref, interaction_statement,"
        " interaction_signature, interaction_key_id)"
        " VALUES (%s, %s, %s, %s, 1, now(), 'INTERNAL', 'WEB_SESSION', %s, %s, %s, %s)",
        (run_id, episode, project, actor, ref, *att),
    )


def test_a_statement_is_bound_to_its_row_and_never_changes(lab, world, tmp_path, db, keys):
    from lab_brain.security.interaction_attestation import (
        ClaimLevel,
        InteractionTrust,
        audit_claims,
        interaction_key_id,
    )

    ada_id, project = world["ada"].actor_id, world["ada_project"]
    ref = _session_ref(db, _signed_in(tmp_path, lab, "ada@uni.example.edu"))
    one, two = _episode(db, project, "epi:one"), _episode(db, project, "epi:two")
    key = keys["key"]
    kid = interaction_key_id(key.public_key)
    binding = {
        "research_run_id": "rrn:one",
        "episode_id": one,
        "trace_id": f"trc:{one}",
        "actor_id": ada_id,
        "project_id": project,
        "session_audit_ref": ref,
    }
    text, sig = _signed(key, **binding)
    _insert_attested(db, "rrn:one", one, project, ada_id, ref, (text, sig, kid))
    trust = InteractionTrust.from_environment()
    assert audit_claims(db, trust)["rrn:one"].level is ClaimLevel.INTERACTION_VERIFIED

    # The same valid statement and signature, pasted onto another run: refused by the CHECK.
    with pytest.raises(psycopg.Error, match="interaction_names_this_row"):
        _insert_attested(db, "rrn:two", two, project, ada_id, ref, (text, sig, kid))
    # A statement for another trace than the row's episode: refused by the trigger.
    other_trace, sig_t = _signed(
        key, **{**binding, "research_run_id": "rrn:two", "episode_id": two, "trace_id": "trc:x"}
    )
    with pytest.raises(psycopg.Error, match="names trace"):
        _insert_attested(db, "rrn:two", two, project, ada_id, ref, (other_trace, sig_t, kid))
    # A nonce is used once.
    reused, sig_r = _signed(
        key,
        **{**binding, "research_run_id": "rrn:two", "episode_id": two, "trace_id": f"trc:{two}"},
    )
    with pytest.raises(psycopg.Error, match="nonce"):
        _insert_attested(db, "rrn:two", two, project, ada_id, ref, (reused, sig_r, kid))
    # Never on a run of another origin; all or none.
    with pytest.raises(psycopg.Error, match="all_or_none"):
        _insert_attested(db, "rrn:two", two, project, ada_id, ref, (reused, None, kid))  # type: ignore[arg-type]

    # Immutable: not changed, erased, or swapped.
    for change, params in (
        (
            "SET interaction_statement = NULL, interaction_signature = NULL,"
            " interaction_key_id = NULL",
            (),
        ),
        ("SET interaction_signature = %s", (base64.b64encode(bytes(64)).decode(),)),
    ):
        with pytest.raises(psycopg.Error, match="never changed"):
            db.execute(f"UPDATE research_runs {change} WHERE research_run_id = 'rrn:one'", params)
    # A run recorded without one cannot be given one later.
    _forge(db, "rrn:bare", two, project, ada_id, ref)
    late, sig_l = _signed(
        key,
        **{
            **binding,
            "research_run_id": "rrn:bare",
            "episode_id": two,
            "trace_id": f"trc:{two}",
            "nonce": "cd" * 16,
        },
    )
    with pytest.raises(psycopg.Error, match="never changed, added or erased"):
        db.execute(
            "UPDATE research_runs SET interaction_statement = %s, interaction_signature = %s,"
            " interaction_key_id = %s WHERE research_run_id = 'rrn:bare'",
            (late, sig_l, kid),
        )
    assert audit_claims(db, trust)["rrn:bare"].level is ClaimLevel.SESSION_RECORDED_UNVERIFIED

    # A report carries the run's own attestation or none -- never another's.
    db.execute(
        "UPDATE research_runs SET finished_at = now(), outcome = 'SUSPENDED:PROVISIONAL'"
        " WHERE research_run_id = 'rrn:bare'"
    )

    def report(**extra: object) -> str:
        return json.dumps(
            {
                "episode_id": two,
                "project_id": project,
                "actor_id": ada_id,
                "episode_state": "SUSPENDED",
                "conclusion": {"status": "PROVISIONAL"},
                "provenance": ["research run `rrn:bare`"],
                "session_provenance": {
                    "origin": "WEB_SESSION",
                    "session_audit_ref": ref,
                    "research_run_id": "rrn:bare",
                    "actor_id": ada_id,
                    "project_id": project,
                    "trace_id": f"trc:{two}",
                    **extra,
                },
            }
        )

    insert = (
        "INSERT INTO research_run_reports (research_run_id, episode_id, project_id, report,"
        " recorded_at) VALUES ('rrn:bare', %s, %s, %s::jsonb, now())"
    )
    with pytest.raises(psycopg.Error, match="misstates its interaction attestation"):
        db.execute(
            insert,
            (
                two,
                project,
                report(
                    interaction_statement=text, interaction_signature=sig, interaction_key_id=kid
                ),
            ),
        )
    db.execute(insert, (two, project, report()))


def test_unpinned_retired_and_tampered_signatures_do_not_verify(lab, world, tmp_path, db, keys):
    from lab_brain.security.interaction_attestation import (
        ClaimLevel,
        InteractionTrust,
        audit_claims,
        interaction_key_id,
    )

    ada_id, project = world["ada"].actor_id, world["ada_project"]
    ref = _session_ref(db, _signed_in(tmp_path, lab, "ada@uni.example.edu"))
    stranger = SigningKey.generate()  # a key a database writer made up: never pinned
    cases: dict[str, tuple[str, str, str]] = {}
    for n, name in enumerate(("unpinned", "retired", "tampered")):
        episode = _episode(db, project, f"epi:{name}")
        key = stranger if name == "unpinned" else keys["key"]
        text, sig = _signed(
            key,
            research_run_id=f"rrn:{name}",
            episode_id=episode,
            trace_id=f"trc:{episode}",
            actor_id=ada_id,
            project_id=project,
            session_audit_ref=ref,
            nonce=f"{n:032x}",
        )
        if name == "tampered":
            # Same fields the CHECK reads; the signing time is changed after signing.
            data = json.loads(text)
            data["signed_at"] = (dt.datetime.now(dt.UTC) - dt.timedelta(days=1)).isoformat()
            from lab_brain.core.canonical_json import canonicalize

            text = canonicalize(data)
        cases[name] = (text, sig, interaction_key_id(key.public_key))
        _insert_attested(db, f"rrn:{name}", episode, project, ada_id, ref, cases[name])
    # Retire the real key before every statement here was signed.
    keys["authorities"].write_text(
        f"web:primary ed25519:{keys['key'].public_key} until=2020-01-01T00:00:00+00:00\n"
    )
    retired = audit_claims(db, InteractionTrust.from_environment())
    assert retired["rrn:retired"].level is ClaimLevel.SESSION_RECORDED_UNVERIFIED
    assert "retired" in retired["rrn:retired"].reason
    keys["authorities"].write_text(f"web:primary ed25519:{keys['key'].public_key}\n")
    claims = audit_claims(db, InteractionTrust.from_environment())
    assert claims["rrn:retired"].level is ClaimLevel.INTERACTION_VERIFIED
    assert claims["rrn:unpinned"].level is ClaimLevel.SESSION_RECORDED_UNVERIFIED
    assert "not a pinned key" in claims["rrn:unpinned"].reason
    assert claims["rrn:tampered"].level is ClaimLevel.SESSION_RECORDED_UNVERIFIED
    assert "does not verify" in claims["rrn:tampered"].reason
