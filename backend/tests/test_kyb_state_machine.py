"""Tests unitarios de la máquina de estados KYB (Fase 1). Sin I/O."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kyb.state_machine import (CLIENT_READONLY_STATES, TRANSITIONS,
                               ForbiddenTransitionError,
                               InvalidTransitionError, KybStateError,
                               client_can_edit, editable_sections,
                               transition_fields, validate_transition)


# ---------------------------------------------------------------------------
# Todas las transiciones válidas
# ---------------------------------------------------------------------------
VALID = [
    ("draft", "in_progress", "client", None, None),
    ("in_progress", "submitted", "client", None, None),
    ("submitted", "screening", "system", None, None),
    ("screening", "under_review", "system", None, None),
    ("under_review", "info_required", "internal", "compliance_officer", None),
    ("info_required", "submitted", "client", None, None),
    ("under_review", "approved", "internal", "compliance_officer", None),
    ("under_review", "rejected", "internal", "compliance_officer", None),
    ("in_progress", "expired", "system", None, None),
    ("info_required", "expired", "system", None, None),
    ("expired", "in_progress", "internal", "admin", None),
    ("approved", "under_review", "system", None, "periodic_review"),
    ("approved", "under_review", "system", None, "provider_alert"),
    ("approved", "under_review", "internal", "admin", "admin"),
]


@pytest.mark.parametrize("frm,to,actor_type,role,reason", VALID)
def test_valid_transitions(frm, to, actor_type, role, reason):
    validate_transition(frm, to, actor_type=actor_type, actor_role=role,
                        reopen_reason=reason)  # no lanza


def test_all_declared_transitions_covered():
    covered = {(f, t) for f, t, *_ in VALID}
    assert covered >= set(TRANSITIONS), \
        f"faltan cubrir: {set(TRANSITIONS) - covered}"


# ---------------------------------------------------------------------------
# Inválidas (>= 6) — una transición no declarada lanza, no falla en silencio
# ---------------------------------------------------------------------------
INVALID = [
    ("draft", "submitted"),          # saltea in_progress
    ("draft", "approved"),
    ("in_progress", "under_review"), # saltea submitted/screening
    ("submitted", "approved"),       # saltea revisión
    ("screening", "approved"),
    ("approved", "rejected"),        # aprobado no pasa directo a rechazado
    ("expired", "submitted"),
    ("under_review", "draft"),       # no hay vuelta atrás
]


@pytest.mark.parametrize("frm,to", INVALID)
def test_invalid_transitions_raise(frm, to):
    with pytest.raises(InvalidTransitionError):
        validate_transition(frm, to, actor_type="internal",
                            actor_role="super_admin")


def test_unknown_states_raise():
    with pytest.raises(KybStateError):
        validate_transition("nope", "approved", actor_type="internal")
    with pytest.raises(KybStateError):
        validate_transition("draft", "nope", actor_type="internal")
    with pytest.raises(KybStateError):
        validate_transition("draft", "in_progress", actor_type="robot")


# ---------------------------------------------------------------------------
# system JAMÁS puede llegar a rejected
# ---------------------------------------------------------------------------
def test_system_cannot_reject():
    with pytest.raises(ForbiddenTransitionError):
        validate_transition("under_review", "rejected", actor_type="system")


def test_system_cannot_reject_even_from_undeclared_paths():
    for frm in ("draft", "screening", "approved", "submitted"):
        with pytest.raises((ForbiddenTransitionError, InvalidTransitionError)):
            validate_transition(frm, "rejected", actor_type="system")


# ---------------------------------------------------------------------------
# rejected terminal — reabrir solo super_admin
# ---------------------------------------------------------------------------
def test_rejected_is_terminal_for_non_super_admin():
    for role in ("admin", "compliance_officer", "finance", None):
        with pytest.raises(ForbiddenTransitionError):
            validate_transition("rejected", "under_review",
                                actor_type="internal", actor_role=role)


def test_rejected_reopen_super_admin_only_to_under_review():
    validate_transition("rejected", "under_review", actor_type="internal",
                        actor_role="super_admin")  # permitido
    with pytest.raises(ForbiddenTransitionError):
        validate_transition("rejected", "approved", actor_type="internal",
                            actor_role="super_admin")


# ---------------------------------------------------------------------------
# approved → under_review exige reopen_reason tipado
# ---------------------------------------------------------------------------
def test_reopen_requires_reason():
    with pytest.raises(ForbiddenTransitionError):
        validate_transition("approved", "under_review",
                            actor_type="internal", actor_role="admin")
    with pytest.raises(ForbiddenTransitionError):
        validate_transition("approved", "under_review",
                            actor_type="internal", actor_role="admin",
                            reopen_reason="because")


def test_transition_fields_records_reopen_reason():
    f = transition_fields("approved", "under_review",
                          reopen_reason="provider_alert")
    assert f["status"] == "under_review"
    assert f["reopen_reason"] == "provider_alert"


def test_transition_fields_stamps():
    assert "submitted_at" in transition_fields("in_progress", "submitted")
    assert "resolved_at" in transition_fields("under_review", "approved")
    assert "resolved_at" in transition_fields("under_review", "rejected")
    assert "resolved_at" not in transition_fields("draft", "in_progress")


# ---------------------------------------------------------------------------
# Read-only para el cliente
# ---------------------------------------------------------------------------
def test_client_readonly_states():
    for st in ("submitted", "screening", "under_review", "approved",
               "rejected"):
        assert client_can_edit(st) is False, st
    for st in ("draft", "in_progress", "info_required"):
        assert client_can_edit(st) is True, st
    assert CLIENT_READONLY_STATES == {"submitted", "screening",
                                      "under_review", "approved"}


def test_info_required_only_observed_sections_editable():
    case = {"status": "info_required", "sections": {
        "tax_identification": {"status": "completed"},
        "legal_representative": {"status": "observed"},
        "company_data": {"status": "observed"},
        "documentation": {"status": "pending"},
        "team": {"status": "completed"},
    }}
    assert sorted(editable_sections(case)) == ["company_data",
                                               "legal_representative"]


def test_readonly_states_have_no_editable_sections():
    for st in ("submitted", "screening", "under_review", "approved",
               "rejected"):
        assert editable_sections({"status": st, "sections": {
            "team": {"status": "observed"}}}) == []


# ---------------------------------------------------------------------------
# F8-fix (post-diag 6 puntos): ningún camino desde submitted a approved.
# La corrección del endpoint es cosmética si la máquina de estados
# admite el salto. Este test verifica el invariante en la fuente.
# ---------------------------------------------------------------------------
def test_submitted_to_approved_is_not_reachable_directly():
    """No existe la arista submitted → approved. Aprobar sin verificar
    es exactamente lo que este módulo vino a impedir."""
    for actor_type in ("client", "internal", "system"):
        with pytest.raises(InvalidTransitionError):
            validate_transition("submitted", "approved",
                                actor_type=actor_type,
                                actor_role="super_admin")


def test_submitted_and_screening_do_not_reach_approved_in_any_hop():
    """Un solo hop no puede llevar submitted (o screening) a approved.
    approved sólo se alcanza desde under_review."""
    hops_into_approved = [(a, b) for (a, b) in TRANSITIONS if b == "approved"]
    assert hops_into_approved == [("under_review", "approved")]
    hops_from_submitted = [(a, b) for (a, b) in TRANSITIONS if a == "submitted"]
    assert hops_from_submitted == [("submitted", "screening")]
    hops_from_screening = [(a, b) for (a, b) in TRANSITIONS if a == "screening"]
    assert hops_from_screening == [("screening", "under_review")]


def test_no_shortcut_from_submitted_to_terminal_states():
    for terminal in ("approved", "rejected", "expired"):
        with pytest.raises(InvalidTransitionError):
            validate_transition("submitted", terminal, actor_type="internal",
                                actor_role="super_admin")


def test_no_shortcut_from_screening_to_terminal_states():
    for terminal in ("approved", "rejected"):
        with pytest.raises(InvalidTransitionError):
            validate_transition("screening", terminal, actor_type="internal",
                                actor_role="super_admin")


def test_reject_still_only_from_under_review():
    """Refuerzo del invariante paralelo: rechazar tampoco puede saltear
    la revisión."""
    assert [(a, b) for (a, b) in TRANSITIONS if b == "rejected"] \
        == [("under_review", "rejected")]
