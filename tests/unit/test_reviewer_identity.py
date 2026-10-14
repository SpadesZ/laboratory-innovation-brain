"""Causal Warrant Gate V1.1: who answered a warrant review is proved, not claimed.

The V1 audit's A2: `diagnostic_warrant_resolve(..., 'act:pi', ...)` from any connection answered as
the PI, and the gate's separation of duties rested on that string. These tests hold the V1.1
rule without a database: an answer counts only when it is signed under a key that an authority
pinned outside the database enrolled for that person in that project -- and every field of the
answer is in what was signed.
"""

from __future__ import annotations

import base64
import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.review_resolution import ReviewOutcome
from lab_brain.core.models.reviewer import ReviewerEnrolment, key_id
from lab_brain.core.models.warrant import DiagnosticWarrantGrant, GrantVerdict
from lab_brain.core.repositories.warrants import InMemoryDiagnosticWarrantStore, WarrantStoreError
from lab_brain.core.warrant import WarrantResolver
from lab_brain.security.reviewer_identity import (
    IdentityUnverified,
    ReviewAuthority,
    ReviewerSigner,
    ReviewerTrust,
    SigningKey,
    grant_authenticator,
    parse_authorities,
    sign_enrolment,
    sign_revocation,
)
from tests.reviewer_keys import AUTHORITY, AUTHORITY_ACTOR, ENROLLED_AT, TRUST, enrol, key_for

PROJECT = "prj:fibre"
REVIEWER = "act:pi"
T0 = dt.datetime(2026, 10, 14, 9, 0, tzinfo=dt.UTC)


def _relation(relation_id: str = "rel:1", actor: str | None = "act:runner") -> RelationJudgment:
    return RelationJudgment.model_validate(
        {
            "relation_id": relation_id,
            "project_id": PROJECT,
            "from_entity_id": "obs:1",
            "to_entity_id": "hyp:h",
            "relation_type": "SUPPORTS",
            "attributes": {"prediction_id": "prd:h", "outcome": "SPLIT"},
            "supporting_attestation_ids": ("att:1",),
            "actor_id": actor,
            "valid_from": T0 - dt.timedelta(days=1),
            "created_at": T0 - dt.timedelta(days=1),
        }
    )


def _store(*relations: RelationJudgment) -> InMemoryDiagnosticWarrantStore:
    by_id = {r.relation_id: r for r in (relations or (_relation(),))}
    store = InMemoryDiagnosticWarrantStore(relation=lambda _p, r: by_id.get(r))
    for relation in by_id.values():
        store.enqueue_warrant_review(
            review_id=f"rvw:{relation.relation_id}",
            project_id=PROJECT,
            relation_id=relation.relation_id,
            stakes="NORMAL",
            reason="DIAGNOSTIC_WARRANT_MISSING",
            trace_id="trc:1",
            episode_id="epi:1",
            created_at=T0 - dt.timedelta(hours=1),
            estimated_minutes=15,
        )
    return store


def _answer(
    store: InMemoryDiagnosticWarrantStore,
    signer: ReviewerSigner,
    *,
    relation_id: str = "rel:1",
    outcome: ReviewOutcome = ReviewOutcome.APPROVED,
    at: dt.datetime = T0,
) -> DiagnosticWarrantGrant:
    return store.resolve(
        resolution_id=f"res:{relation_id}",
        grant_id=f"dwg:{relation_id}",
        review_id=f"rvw:{relation_id}",
        project_id=PROJECT,
        outcome=outcome,
        signer=signer,
        rationale="splitting is what this mechanism produces and no rival does",
        considered_rival_ids=("hyp:r2", "hyp:r1"),
        resolved_at=at,
    )


# -- keys and the trust anchor -------------------------------------------------------------------


def test_a_key_round_trips_through_its_owner_only_file(tmp_path: Path) -> None:
    key = SigningKey.generate()
    path = tmp_path / "reviewer.key"
    key.save(path, passphrase=b"correct horse")
    loaded = SigningKey.load(path, passphrase=b"correct horse")
    assert loaded.public_key == key.public_key and loaded.key_id == key_id(key.public_key)
    with pytest.raises(FileExistsError):
        key.save(path)  # a key is never written over
    with pytest.raises(IdentityUnverified):
        SigningKey.load(path, passphrase=b"wrong")


def test_the_authorities_file_is_parsed_exactly_or_refused() -> None:
    text = f"# the lab's review authority\n{AUTHORITY_ACTOR} ed25519:{AUTHORITY.public_key}\n"
    (authority,) = parse_authorities(text)
    assert authority.actor_id == AUTHORITY_ACTOR and authority.key_id == AUTHORITY.key_id
    for bad in (
        f"{AUTHORITY_ACTOR} {AUTHORITY.public_key}",  # no algorithm
        f"pi ed25519:{AUTHORITY.public_key}",  # not an actor id
        f"{AUTHORITY_ACTOR} ed25519:not-a-key",
        f"{text}{text}",  # the same key twice
    ):
        with pytest.raises(IdentityUnverified):
            parse_authorities(bad)
    assert not ReviewerTrust.configured_at("").configured


# -- enrolment ------------------------------------------------------------------------------------


def _enrolment(**overrides: Any) -> ReviewerEnrolment:
    fields: dict[str, Any] = {
        "authority_actor_id": AUTHORITY_ACTOR,
        "enrolment_id": "enr:1",
        "project_id": PROJECT,
        "actor_id": REVIEWER,
        "public_key": key_for(REVIEWER).public_key,
        "enrolled_at": ENROLLED_AT,
    }
    authority = overrides.pop("authority", AUTHORITY)
    fields.update(overrides)
    return sign_enrolment(authority, **fields)


def test_only_a_pinned_authority_enrols_and_never_itself() -> None:
    TRUST.verify_enrolment(_enrolment())
    # A key the deployment does not pin, however it names itself.
    rogue = key_for("act:rogue-authority")
    with pytest.raises(IdentityUnverified, match="not a pinned review authority"):
        TRUST.verify_enrolment(_enrolment(authority=rogue))
    # The pinned key, claiming to act for someone else.
    with pytest.raises(IdentityUnverified, match="names act:someone-else as its authority"):
        TRUST.verify_enrolment(_enrolment(authority_actor_id="act:someone-else"))
    # Self-authorization is refused by the record itself.
    with pytest.raises(ValueError, match="cannot enrol their own reviewer key"):
        _enrolment(actor_id=AUTHORITY_ACTOR)
    # No authority configured: nothing verifies.
    with pytest.raises(IdentityUnverified, match="pins no review authority"):
        ReviewerTrust().verify_enrolment(_enrolment())


def test_an_edited_enrolment_no_longer_verifies() -> None:
    enrolment = _enrolment()
    for field, value in (
        ("actor_id", "act:impostor"),
        ("project_id", "prj:other"),
        ("public_key", key_for("act:impostor").public_key),
        ("enrolled_at", ENROLLED_AT - dt.timedelta(days=1)),
    ):
        edited = enrolment.model_copy(update={field: value})
        with pytest.raises(IdentityUnverified, match="signature does not verify"):
            TRUST.verify_enrolment(edited)


# -- answers ----------------------------------------------------------------------------------


def test_an_answer_verifies_under_its_enrolled_key_and_any_edit_breaks_it() -> None:
    store = _store()
    signer = enrol(store, project_id=PROJECT, actor_id=REVIEWER)
    grant = _answer(store, signer)
    authenticate = grant_authenticator(store, TRUST)
    assert authenticate(grant) is None
    for field, value in (
        ("verdict", GrantVerdict.NOT_WARRANTED),
        ("relation_id", "rel:other"),
        ("prediction_id", "prd:other"),
        ("hypothesis_id", "hyp:other"),
        ("rationale", "an answer nobody gave"),
        ("identifies_class_ref", "dds:fibre@1#split"),
        ("considered_rival_ids", ("hyp:r1",)),
        ("granted_at", T0 + dt.timedelta(seconds=1)),
    ):
        edited = grant.model_copy(update={field: value})
        assert authenticate(edited) is not None, field
    # The rivals are part of the answer as a set, not in the order they were typed.
    assert (
        authenticate(grant.model_copy(update={"considered_rival_ids": ("hyp:r1", "hyp:r2")}))
        is None
    )


def test_naming_the_pi_does_not_make_an_answer_the_pis() -> None:
    """A2, the recorded impersonation: the PI's actor id with any key but the PI's."""
    store = _store()
    enrol(store, project_id=PROJECT, actor_id=REVIEWER)
    impostor = ReviewerSigner(
        actor_id=REVIEWER, enrolment_id=f"enr:{PROJECT}:{REVIEWER}", key=key_for("act:impostor")
    )
    grant = _answer(store, impostor)  # the in-memory twin, like SQL, cannot check a signature
    why = grant_authenticator(store, TRUST)(grant)
    assert why is not None and "reviewer's signature does not verify" in why
    unsigned = grant.model_copy(update={"signature": None})
    assert "unsigned" in (grant_authenticator(store, TRUST)(unsigned) or "")


def test_an_enrolment_for_another_person_or_project_proves_nothing_here() -> None:
    store = _store()
    enrol(store, project_id=PROJECT, actor_id="act:colleague")
    borrowed = ReviewerSigner(
        actor_id=REVIEWER, enrolment_id=f"enr:{PROJECT}:act:colleague", key=key_for("act:colleague")
    )
    with pytest.raises(WarrantStoreError, match="is not act:pi's reviewer key"):
        _answer(store, borrowed)


def test_a_revoked_key_answers_nothing_from_its_revocation() -> None:
    store = _store(_relation("rel:1"), _relation("rel:2"))
    signer = enrol(store, project_id=PROJECT, actor_id=REVIEWER)
    before = _answer(store, signer, relation_id="rel:1", at=T0)
    store.revoke(
        sign_revocation(
            AUTHORITY,
            authority_actor_id=AUTHORITY_ACTOR,
            revocation_id="rvk:1",
            enrolment_id=signer.enrolment_id,
            project_id=PROJECT,
            effective_at=T0 + dt.timedelta(hours=1),
            reason="laptop lost",
        )
    )
    authenticate = grant_authenticator(store, TRUST)
    assert authenticate(before) is None, "an answer signed before the revocation still counts"
    with pytest.raises(WarrantStoreError, match="revoked"):
        _answer(store, signer, relation_id="rel:2", at=T0 + dt.timedelta(hours=2))
    late = before.model_copy(update={"granted_at": T0 + dt.timedelta(hours=2)})
    assert "revoked from" in (authenticate(late) or "")


def test_an_answer_cannot_predate_its_key_or_its_question() -> None:
    store = _store()
    signer = enrol(store, project_id=PROJECT, actor_id=REVIEWER, at=T0)
    with pytest.raises(WarrantStoreError, match="cannot predate"):
        _answer(store, signer, at=T0 - dt.timedelta(minutes=5))


# -- the resolver -------------------------------------------------------------------------------


def test_the_resolver_counts_only_answers_that_verify() -> None:
    """An answer that does not verify is no answer: it neither warrants nor refuses."""
    store = _store()
    signer = enrol(store, project_id=PROJECT, actor_id=REVIEWER)
    genuine = _answer(store, signer)

    def resolver(grants: Any) -> WarrantResolver:
        return WarrantResolver(
            certificates=lambda _p, _h: None,
            attestations=lambda _p, _a: None,
            observations=lambda _p, _o: None,
            runs=lambda _r: None,
            grants=grants,
            authenticate=grant_authenticator(store, TRUST),
        )

    (counted,) = resolver(store).resolve(PROJECT, "hyp:h", (_relation(),)).records
    assert counted.warrant is not None and counted.warrant_ref == genuine.grant_id

    class Forged:
        def grants_for_relations(self, _project: str, _ids: Any) -> tuple[Any, ...]:
            return (genuine.model_copy(update={"rationale": "edited after signing"}),)

        def grant(self, _project: str, _grant_id: str) -> Any:
            return None

    forged = resolver(Forged())
    (record,) = forged.resolve(PROJECT, "hyp:h", (_relation(),)).records
    assert record.warrant is None and not record.refused
    assert "rel:1" in forged.unverified_answers(PROJECT, ["rel:1"])


def test_a_relation_type_mismatch_is_rejected_by_the_answer_model() -> None:
    with pytest.raises(ValueError):
        DiagnosticWarrantGrant(
            grant_id="dwg:x",
            project_id=PROJECT,
            review_id="rvw:x",
            relation_id="rel:x",
            relation_type=RelationType.PREDICTS,
            hypothesis_id="hyp:h",
            prediction_id="prd:h",
            verdict=GrantVerdict.WARRANTED,
            granted_by_actor_id=REVIEWER,
            granted_at=T0,
            rationale="r",
        )


def test_signatures_are_ed25519_shaped() -> None:
    raw = base64.b64decode(key_for(REVIEWER).sign(b"x"))
    assert len(raw) == 64
    assert ReviewAuthority(AUTHORITY_ACTOR, AUTHORITY.public_key).key_id.startswith("rk:")


def test_a_key_or_signature_has_exactly_one_spelling() -> None:
    """Base64 tolerates non-zero padding bits; a second spelling of one key or signature would be
    a second string the database compares. Only the canonical spelling is a key or a signature."""
    from lab_brain.core.models.reviewer import is_public_key, is_signature

    public = key_for(REVIEWER).public_key
    signature = key_for(REVIEWER).sign(b"x")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

    def respelled(value: str, pad: int) -> str:
        last = value[-pad - 1]
        twin = alphabet[alphabet.index(last) + 1]
        return value[: -pad - 1] + twin + value[-pad:]

    assert is_public_key(public) and not is_public_key(respelled(public, 1))
    assert base64.b64decode(respelled(public, 1)) == base64.b64decode(public)
    assert is_signature(signature) and not is_signature(respelled(signature, 2))


def test_no_pinned_authority_key_is_ever_a_reviewer_key() -> None:
    """With two authorities pinned, one cannot enrol the other's key as a reviewer's."""
    second = key_for("act:second-authority")
    trust = ReviewerTrust(
        (
            ReviewAuthority(AUTHORITY_ACTOR, AUTHORITY.public_key),
            ReviewAuthority("act:second-authority", second.public_key),
        )
    )
    trust.verify_enrolment(_enrolment())
    with pytest.raises(IdentityUnverified, match="an authority key is not a reviewer key"):
        trust.verify_enrolment(_enrolment(public_key=second.public_key))


def _resigned(
    grant: DiagnosticWarrantGrant, key: SigningKey, **changes: Any
) -> DiagnosticWarrantGrant:
    """`grant` with `changes`, signed again -- validly -- with `key`: what a key holder could do."""
    changed = grant.model_copy(update=changes)
    return changed.model_copy(update={"signature": key.sign(changed.statement())})


def test_a_validly_signed_answer_still_cannot_predate_its_key() -> None:
    """Signed by the right key, and still refused: the enrolment did not exist yet."""
    store = _store()
    signer = enrol(store, project_id=PROJECT, actor_id=REVIEWER, at=T0 - dt.timedelta(hours=2))
    grant = _answer(store, signer)
    authenticate = grant_authenticator(store, TRUST)
    assert authenticate(grant) is None
    early = _resigned(grant, signer.key, granted_at=T0 - dt.timedelta(hours=3))
    assert "predates the enrolment" in (authenticate(early) or "")


def test_a_validly_signed_answer_under_another_persons_enrolment_is_not_theirs() -> None:
    """A colleague's key signs perfectly; the answer names the PI, so it is not the PI's."""
    store = _store()
    colleague = enrol(store, project_id=PROJECT, actor_id="act:colleague")
    mine = enrol(store, project_id=PROJECT, actor_id=REVIEWER)
    grant = _answer(store, mine)
    borrowed = _resigned(grant, colleague.key, enrolment_id=colleague.enrolment_id)
    why = grant_authenticator(store, TRUST)(borrowed) or ""
    assert "is by act:pi" in why and "act:colleague's" in why


def test_a_retired_authority_still_vouches_for_what_it_signed_before_and_nothing_after() -> None:
    """Rotation: the old authority stays pinned `until` the switch, so answers given under it keep
    counting, and nothing it signs afterwards does."""
    retired = parse_authorities(
        f"{AUTHORITY_ACTOR} ed25519:{AUTHORITY.public_key} until=2026-06-01T00:00:00+00:00\n"
    )
    trust = ReviewerTrust(retired)
    trust.verify_enrolment(_enrolment(enrolled_at=dt.datetime(2026, 5, 1, tzinfo=dt.UTC)))
    with pytest.raises(IdentityUnverified, match="authority was retired"):
        trust.verify_enrolment(_enrolment(enrolled_at=dt.datetime(2026, 7, 1, tzinfo=dt.UTC)))
    with pytest.raises(IdentityUnverified, match="needs a time zone"):
        parse_authorities(f"{AUTHORITY_ACTOR} ed25519:{AUTHORITY.public_key} until=2026-06-01\n")


def test_a_named_but_unusable_authorities_file_stops_the_command_before_it_connects(
    tmp_path: Path,
) -> None:
    import io

    from lab_brain.interfaces import cli

    bad = tmp_path / "authorities"
    bad.write_text("act:pi not-a-key\n", encoding="utf-8")

    def refuse(_settings: Any) -> Any:
        raise AssertionError("connected before the trust anchor was checked")

    for path in (str(bad), str(tmp_path / "missing")):
        out = io.StringIO()
        code = cli.main(
            ["review", "list", "--project", "prj:x", "--actor", "act:pi"],
            out=out,
            env={
                "LAB_BRAIN_DATABASE_URL": "postgresql://unused",
                "LAB_BRAIN_REVIEW_AUTHORITIES": path,
            },
            connect=refuse,
        )
        assert code == 2 and "review authorities file" in out.getvalue(), out.getvalue()
