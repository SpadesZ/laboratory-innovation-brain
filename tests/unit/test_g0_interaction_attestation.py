"""G0-A interaction attestation (`011q`), without a database.

The statement is canonical and binds the run; the pinned keys live outside the database and
rotate with `until`; an unpinned, retired, tampered or copied statement does not verify; with no
key pinned nothing verifies; the claim level is computed when the report is shown, never read from
a stored verdict; only INTERACTION_VERIFIED is described as an authenticated interaction, in both
languages, and the parity checker catches a rendering that says otherwise. The database rules and
the real web flow are in `tests/e2e/test_g0_interaction_attestation_postgres.py`.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path

import pytest

from lab_brain.core.canonical_json import canonicalize
from lab_brain.interfaces.web import pages
from lab_brain.interfaces.web.bilingual_parity import check_html, check_markdown
from lab_brain.interfaces.web.i18n import Messages
from lab_brain.research.render import render_markdown
from lab_brain.research.report import SessionProvenance
from lab_brain.research.report_store import report_from_json, report_to_json
from lab_brain.research.run_provenance import (
    ClaimLevel,
    ProvenanceRefused,
    RunBinding,
    RunOrigin,
    RunProvenance,
)
from lab_brain.security.interaction_attestation import (
    AUTHORITIES_ENV,
    SIGNING_KEY_ENV,
    InteractionAttestation,
    InteractionAuthority,
    InteractionSigner,
    InteractionStatement,
    InteractionTrust,
    InteractionUnverified,
    WebInteraction,
    interaction_claim,
    parse_interaction_authorities,
)
from lab_brain.security.reviewer_identity import SigningKey
from tests.unit.test_g0_bilingual_export_markdown import CANONICAL, _report, _terms

REF = "sar:" + "0123456789abcdef" * 2
T = dt.datetime(2026, 10, 28, 9, 0, tzinfo=dt.UTC)
BINDING = RunBinding(
    research_run_id="rrn:one",
    episode_id="epi:full",
    trace_id="trc:one",
    actor_id="act:ada",
    project_id="prj:rs",
    session_audit_ref=REF,
)


def _signer(key: SigningKey | None = None, at: dt.datetime = T) -> InteractionSigner:
    return InteractionSigner(key or SigningKey.generate(), clock=lambda: at)


def _trust(*signers: InteractionSigner, until: dt.datetime | None = None) -> InteractionTrust:
    return InteractionTrust(
        [InteractionAuthority(f"web:{n}", s.public_key, until) for n, s in enumerate(signers)]
    )


def _attest(signer: InteractionSigner, binding: RunBinding = BINDING, route: str = "/runs"):  # type: ignore[no-untyped-def]
    return WebInteraction(route=route, method="POST", signer=signer).attest(binding)


def test_the_statement_is_canonical_and_binds_every_field():
    signer = _signer()
    att = _attest(signer)
    statement = InteractionStatement.parse(att.statement)
    assert statement.binding == BINDING
    assert (statement.route, statement.method, statement.csrf_verified) == ("/runs", "POST", True)
    assert (statement.kind, statement.version, statement.signed_at) == (
        "lab-brain/research-interaction",
        1,
        T,
    )
    assert att.statement == canonicalize(json.loads(att.statement))
    assert att.key_id == signer.key_id and att.key_id.startswith("ik:")
    assert _attest(signer).statement != att.statement  # a fresh nonce each time
    for bad in (
        att.statement.replace('"csrf_verified":true', '"csrf_verified":false'),
        att.statement.replace('"version":1', '"version":2'),
        att.statement.replace("{", "{ ", 1),  # not canonical
        json.dumps({**json.loads(att.statement), "extra": 1}),
        "not json",
    ):
        with pytest.raises(InteractionUnverified):
            InteractionStatement.parse(bad)


def test_a_signature_verifies_only_under_a_pinned_key_for_exactly_its_run():
    signer = _signer()
    att = _attest(signer)
    trust = _trust(signer)
    trust.verify(att, BINDING)
    assert trust.claim("WEB_SESSION", BINDING, att).level is ClaimLevel.INTERACTION_VERIFIED
    refusals = {
        "no key pinned": (InteractionTrust(), att, BINDING),
        "unpinned key": (_trust(_signer()), att, BINDING),
        "copied to another run": (
            trust,
            att,
            dataclasses.replace(BINDING, research_run_id="rrn:two"),
        ),
        "another session": (
            trust,
            att,
            dataclasses.replace(BINDING, session_audit_ref="sar:" + "f" * 32),
        ),
        "another trace": (trust, att, dataclasses.replace(BINDING, trace_id="trc:x")),
        "tampered statement": (
            trust,
            dataclasses.replace(att, statement=att.statement.replace("T09:00", "T08:00")),
            BINDING,
        ),
        "signature of another statement": (
            trust,
            dataclasses.replace(att, signature=_attest(signer).signature),
            BINDING,
        ),
        "key id swapped": (trust, dataclasses.replace(att, key_id="ik:" + "0" * 32), BINDING),
        "another route": (trust, _attest(signer, route="/settings/llm"), BINDING),
        "continue route of another episode": (
            trust,
            _attest(signer, route="/episodes/epi:other/continue"),
            BINDING,
        ),
    }
    for name, (t, a, b) in refusals.items():
        with pytest.raises(InteractionUnverified):
            t.verify(a, b)
        claim = t.claim("WEB_SESSION", b, a)
        assert claim.level is ClaimLevel.SESSION_RECORDED_UNVERIFIED, name
        assert not claim.authenticated_interaction
    _trust(signer).verify(_attest(signer, route="/episodes/epi:full/continue"), BINDING)


def test_a_retired_key_verifies_only_what_it_signed_before_retirement():
    key = SigningKey.generate()
    before, after = _signer(key, T), _signer(key, T + dt.timedelta(hours=2))
    trust = _trust(before, until=T + dt.timedelta(hours=1))
    trust.verify(_attest(before), BINDING)
    with pytest.raises(InteractionUnverified, match="retired"):
        trust.verify(_attest(after), BINDING)


def test_the_authorities_file_is_strict(tmp_path: Path):
    key = SigningKey.generate()
    good = f"# pinned\nweb:primary ed25519:{key.public_key} until=2027-01-01T00:00:00+00:00\n"
    (authority,) = parse_interaction_authorities(good)
    assert authority.valid_until == dt.datetime(2027, 1, 1, tzinfo=dt.UTC)
    for bad in (
        f"act:primary ed25519:{key.public_key}",  # a reviewer authority line is not one
        "web:primary ed25519:not-a-key",
        f"web:primary ed25519:{key.public_key} until=2027-01-01T00:00:00",
        f"web:a ed25519:{key.public_key}\nweb:b ed25519:{key.public_key}",
    ):
        with pytest.raises(InteractionUnverified):
            parse_interaction_authorities(bad)
    broken = tmp_path / "broken"
    broken.write_text("garbage line\n")
    with pytest.raises(InteractionUnverified):
        InteractionTrust.from_environment({AUTHORITIES_ENV: str(broken)})
    # Shown on a page, a broken file pins nothing: every run reads unverified, nothing crashes.
    assert not InteractionTrust.for_display({AUTHORITIES_ENV: str(broken)}).configured
    assert not InteractionTrust.from_environment({}).configured


def test_the_signer_is_optional_and_never_shows_its_key(tmp_path: Path):
    assert InteractionSigner.from_environment({}) is None
    key = SigningKey.generate()
    path = tmp_path / "k.pem"
    key.save(path)
    signer = InteractionSigner.from_environment({SIGNING_KEY_ENV: str(path)})
    assert signer is not None and signer.public_key == key.public_key
    pem = path.read_text()
    body = "".join(pem.splitlines()[1:-1])
    assert body not in repr(signer) and body not in str(_attest(signer))
    with pytest.raises(InteractionUnverified):
        InteractionSigner.from_environment({SIGNING_KEY_ENV: str(tmp_path / "missing.pem")})


def test_only_a_web_session_provenance_carries_an_attestor():
    web = WebInteraction(route="/runs", method="POST", signer=_signer())
    assert RunProvenance.web_session(REF, web).attestor is web
    assert RunProvenance.web_session(REF, web) == RunProvenance.web_session(REF)
    with pytest.raises(ProvenanceRefused):
        RunProvenance(RunOrigin.OPERATOR_CLI, None, web)


# -- the report, in both languages ----------------------------------------------------------------


def _with(origin: RunOrigin, att: InteractionAttestation | None = None):  # type: ignore[no-untyped-def]
    return dataclasses.replace(
        _report(),
        session_provenance=SessionProvenance(
            origin=origin.value,
            session_audit_ref=REF if origin is RunOrigin.WEB_SESSION else None,
            actor_id="act:ada",
            project_id="prj:rs",
            research_run_id="rrn:one",
            trace_id="trc:one",
            interaction_statement=None if att is None else att.statement,
            interaction_signature=None if att is None else att.signature,
            interaction_key_id=None if att is None else att.key_id,
        ),
    )


def _md(report, locale):  # type: ignore[no-untyped-def]
    return pages.markdown_export(report, (), terms=_terms(locale), canonical_digest=CANONICAL)


def _page(report, locale):  # type: ignore[no-untyped-def]
    return pages.episode_page(
        actor_id="act:1",
        episode=pages.EpisodeRow(
            "epi:full",
            "prj:rs",
            "trc:one",
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
        chrome=pages.Chrome("act:1", locale),
        terms=_terms(locale),
    ).decode()


@pytest.fixture
def pinned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> InteractionSigner:
    signer = _signer()
    authorities = tmp_path / "authorities"
    authorities.write_text(f"web:primary ed25519:{signer.public_key}\n")
    monkeypatch.setenv(AUTHORITIES_ENV, str(authorities))
    return signer


def _cases(signer: InteractionSigner):  # type: ignore[no-untyped-def]
    assert _report().episode_id == BINDING.episode_id
    stranger = _signer()
    return {
        ClaimLevel.INTERACTION_VERIFIED: _with(RunOrigin.WEB_SESSION, _attest(signer)),
        ClaimLevel.SESSION_RECORDED_UNVERIFIED: _with(RunOrigin.WEB_SESSION),
        "unpinned": _with(RunOrigin.WEB_SESSION, _attest(stranger)),
        ClaimLevel.OPERATOR_UNATTESTED: _with(RunOrigin.OPERATOR_CLI),
        ClaimLevel.LEGACY_UNATTESTED: _with(RunOrigin.LEGACY_UNATTESTED),
    }


def test_each_claim_level_is_stated_the_same_in_both_languages_and_never_overstated(pinned):
    verified = {
        loc: Messages(loc)("md.session.says.INTERACTION_VERIFIED").removeprefix("- ")
        for loc in ("en", "zh-TW")
    }
    for case, report in _cases(pinned).items():
        level = ClaimLevel.SESSION_RECORDED_UNVERIFIED if case == "unpinned" else ClaimLevel(case)
        assert interaction_claim(report).level is level
        assert report_from_json(report_to_json(report)) == report
        en, zh = _md(report, "en"), _md(report, "zh-TW")
        assert render_markdown(report) in en or en.startswith(render_markdown(report)[:200])
        result = check_markdown(en, zh)
        assert result.ok, (case, result.findings)
        page = {loc: _page(report, loc) for loc in ("en", "zh-TW")}
        html = check_html(page["en"], page["zh-TW"], surface="page")
        assert html.ok, (case, html.findings)
        for loc, text in (("en", en), ("zh-TW", zh), ("en", page["en"]), ("zh-TW", page["zh-TW"])):
            assert level.value in text
            assert (verified[loc] in text) is (level is ClaimLevel.INTERACTION_VERIFIED)
            assert ("INTERACTION_VERIFIED" in text) is (level is ClaimLevel.INTERACTION_VERIFIED)
        if level is not ClaimLevel.INTERACTION_VERIFIED:
            # Every other level says what is NOT shown.
            said = Messages("en")(f"md.session.says.{level.value}")
            assert said in en and any(w in said for w in ("not", "No", "nothing"))
            zh_said = Messages("zh-TW")(f"md.session.says.{level.value}")
            assert zh_said in zh and any(c in zh_said for c in "未沒")


def test_a_stored_verdict_is_never_trusted_and_no_key_means_unverified(pinned, monkeypatch):
    report = _cases(pinned)[ClaimLevel.INTERACTION_VERIFIED]
    # The same stored report, in a deployment that pins no key: unverified, and says so.
    monkeypatch.delenv(AUTHORITIES_ENV)
    assert interaction_claim(report).level is ClaimLevel.SESSION_RECORDED_UNVERIFIED
    text = render_markdown(report)
    assert "SESSION_RECORDED_UNVERIFIED" in text and "INTERACTION_VERIFIED" not in text
    # A report field cannot assert a level: there is none to set.
    data = report_to_json(report)
    data["session_provenance"]["claim_level"] = "INTERACTION_VERIFIED"
    with pytest.raises(ValueError, match="no field"):
        report_from_json(data)


def test_parity_catches_a_raised_or_overstated_claim(pinned):
    unverified = _with(RunOrigin.WEB_SESSION)
    en, zh = _md(unverified, "en"), _md(unverified, "zh-TW")
    raised = zh.replace("SESSION_RECORDED_UNVERIFIED", "INTERACTION_VERIFIED")
    assert "AUTH_CLAIM" in check_markdown(en, raised).checks()
    overstated = en + "\n" + Messages("en")("md.session.says.INTERACTION_VERIFIED") + "\n"
    assert "AUTH_CLAIM" in check_markdown(overstated, zh).checks()
    page_en, page_zh = _page(unverified, "en"), _page(unverified, "zh-TW")
    assert (
        "AUTH_CLAIM"
        in check_html(
            page_en,
            page_zh.replace("SESSION_RECORDED_UNVERIFIED", "INTERACTION_VERIFIED"),
            surface="page",
        ).checks()
    )
