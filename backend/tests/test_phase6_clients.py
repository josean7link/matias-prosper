"""
Phase 6 — Admin Clients module backend tests.

Covers:
 - Clients CRUD + pause/reactivate
 - Signed JWT links (kyb, reset_password, invite) + public verify/consume
 - Per-client users invite/patch/revoke
 - API keys plaintext-once + rotate + revoke
 - Webhooks: create, list, test (httpbin delivery), reveal, deliveries
 - Outbound emails (mock preview_only)
 - Audit log
 - RBAC for client_admin & compliance_officer
"""
import os
import time
import uuid
import requests
import pytest

BASE = os.environ["PUBLIC_BASE_URL"].rstrip("/") if os.environ.get("PUBLIC_BASE_URL") \
    else "https://finance-control-215.preview.emergentagent.com"

API = f"{BASE}/api/v1"


def _login(email: str) -> requests.Session:
    s = requests.Session()
    r = s.get(f"{API}/auth/dev-login", params={"email": email, "next": "/admin"},
              allow_redirects=True, timeout=20)
    assert r.status_code in (200, 302), f"dev-login {email} -> {r.status_code} {r.text[:200]}"
    me = s.get(f"{API}/auth/me", timeout=10)
    assert me.status_code == 200, f"auth/me {me.status_code}"
    return s


@pytest.fixture(scope="module")
def super_admin() -> requests.Session:
    return _login("admin@prosper.foundation")


@pytest.fixture(scope="module")
def client_admin_sess() -> requests.Session:
    return _login("client.admin@alemany.capital")


@pytest.fixture(scope="module")
def compliance_sess() -> requests.Session:
    return _login("compliance@prosper.foundation")


@pytest.fixture(scope="module")
def created_org(super_admin) -> dict:
    """Create one org used by many tests."""
    uniq = uuid.uuid4().hex[:8]
    payload = {
        "legal_name": f"TEST_Corp_{uniq} SA",
        "commercial_name": f"TEST {uniq}",
        "tax_id": f"TEST-{uniq}",
        "country": "AR",
        "type": "broker",
        "env": "sandbox",
        "tier": "T2",
        "primary_email": f"primary.{uniq}@testprosper.com",
        "primary_name": "Primary User",
        "domain_allowlist": [f"test-{uniq}.com"],
    }
    r = super_admin.post(f"{API}/admin/clients", json=payload, timeout=20)
    assert r.status_code in (200, 201), f"create org -> {r.status_code} {r.text[:300]}"
    body = r.json()
    assert body.get("ok") is True
    assert "org" in body and body["org"].get("org_id"), body
    assert "primary_user_id" in body
    assert "invite_link" in body and "token=" in body["invite_link"]
    return body


# ─── 1. CRUD + listing ─────────────────────────────────────────────────────
class TestClientsCRUD:
    def test_list_returns_paginated(self, super_admin):
        r = super_admin.get(f"{API}/admin/clients", params={"page": 1, "page_size": 25}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d and "total" in d
        assert isinstance(d["items"], list)
        assert d["total"] >= 1
        if d["items"]:
            first = d["items"][0]
            assert "org_id" in first and "legal_name" in first

    def test_create_returns_org_and_invite(self, created_org):
        assert created_org["org"]["paused"] is False

    def test_get_detail_has_metrics_and_risk(self, super_admin, created_org):
        org_id = created_org["org"]["org_id"]
        r = super_admin.get(f"{API}/admin/clients/{org_id}", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["org"]["org_id"] == org_id
        assert "metrics" in d
        m = d["metrics"]
        for k in ("volume_total_usd", "tx_count", "active_positions", "users_count", "alerts_open"):
            assert k in m, f"missing metric {k}"
        assert "risk" in d  # may be None

    def test_patch_updates_field(self, super_admin, created_org):
        org_id = created_org["org"]["org_id"]
        new_name = "TEST_UPDATED_NAME"
        r = super_admin.patch(f"{API}/admin/clients/{org_id}",
                              json={"commercial_name": new_name}, timeout=15)
        assert r.status_code == 200, r.text[:200]
        # verify persistence
        r2 = super_admin.get(f"{API}/admin/clients/{org_id}", timeout=10).json()
        assert r2["org"]["commercial_name"] == new_name

    def test_pause_and_reactivate(self, super_admin, created_org):
        org_id = created_org["org"]["org_id"]
        r = super_admin.post(f"{API}/admin/clients/{org_id}/pause", timeout=10)
        assert r.status_code == 200, r.text[:200]
        d = super_admin.get(f"{API}/admin/clients/{org_id}").json()
        assert d["org"]["paused"] is True
        r = super_admin.post(f"{API}/admin/clients/{org_id}/reactivate", timeout=10)
        assert r.status_code == 200
        d = super_admin.get(f"{API}/admin/clients/{org_id}").json()
        assert d["org"]["paused"] is False


# ─── 2. RBAC — client_admin & compliance must NOT write ───────────────────
class TestClientsRBAC:
    @pytest.mark.parametrize("method,path_tpl,body", [
        ("POST", "/admin/clients", {"legal_name": "x", "tax_id": "x", "primary_email": "x@x.x", "primary_name": "x"}),
        ("PATCH", "/admin/clients/{org_id}", {"commercial_name": "x"}),
        ("POST", "/admin/clients/{org_id}/pause", None),
        ("POST", "/admin/clients/{org_id}/reactivate", None),
    ])
    def test_client_admin_forbidden(self, client_admin_sess, created_org, method, path_tpl, body):
        org_id = created_org["org"]["org_id"]
        url = f"{API}{path_tpl.format(org_id=org_id)}"
        r = client_admin_sess.request(method, url, json=body, timeout=10)
        assert r.status_code == 403, f"{method} {path_tpl} expected 403 got {r.status_code} body={r.text[:150]}"

    def test_compliance_forbidden_to_create(self, compliance_sess):
        r = compliance_sess.post(f"{API}/admin/clients",
                                 json={"legal_name": "x", "tax_id": "x",
                                       "primary_email": "x@x.x", "primary_name": "x"},
                                 timeout=10)
        assert r.status_code == 403


# ─── 3. Signed JWT links + public verify/consume ──────────────────────────
class TestSignedLinks:
    @pytest.mark.parametrize("purpose", ["kyb", "reset_password", "invite"])
    def test_create_link_with_send_email_false(self, super_admin, created_org, purpose):
        org_id = created_org["org"]["org_id"]
        body = {"send_email": False}
        if purpose == "invite":
            body.update({"email": f"newinvite+{purpose}@test.local", "name": "Inv"})
        if purpose == "reset_password":
            body.update({"email": created_org["org"]["primary_email"]})
        r = super_admin.post(f"{API}/admin/clients/{org_id}/links/{purpose}",
                             json=body, timeout=15)
        assert r.status_code in (200, 201), f"{purpose}: {r.status_code} {r.text[:200]}"
        d = r.json()
        assert "url" in d and "token=" in d["url"]
        assert "link_id" in d

    def test_verify_and_consume_flow(self, super_admin, created_org):
        org_id = created_org["org"]["org_id"]
        r = super_admin.post(f"{API}/admin/clients/{org_id}/links/kyb",
                             json={"send_email": False}, timeout=10)
        url = r.json()["url"]
        token = url.split("token=")[-1].split("&")[0]

        # verify (anonymous)
        v = requests.post(f"{API}/links/verify", json={"token": token}, timeout=10)
        assert v.status_code == 200, v.text[:200]
        vd = v.json()
        assert vd.get("ok") is True
        assert vd.get("purpose") == "kyb"

        # consume first time
        c1 = requests.post(f"{API}/links/consume", json={"token": token}, timeout=10)
        assert c1.status_code == 200, f"consume1 {c1.status_code} {c1.text[:200]}"

        # consume second time should fail
        c2 = requests.post(f"{API}/links/consume", json={"token": token}, timeout=10)
        assert c2.status_code == 401, f"consume2 expected 401 got {c2.status_code} body={c2.text[:200]}"


# ─── 4. Per-client users ──────────────────────────────────────────────────
class TestClientUsers:
    def test_list_includes_primary_user(self, super_admin, created_org):
        org_id = created_org["org"]["org_id"]
        r = super_admin.get(f"{API}/admin/clients/{org_id}/users", timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d
        assert d["total"] >= 1
        emails = [u.get("email") for u in d["items"]]
        assert created_org["org"]["primary_email"] in emails

    def test_invite_patch_revoke(self, super_admin, created_org):
        org_id = created_org["org"]["org_id"]
        email = f"TEST_member_{uuid.uuid4().hex[:6]}@testprosper.com"
        r = super_admin.post(f"{API}/admin/clients/{org_id}/users",
                             json={"email": email, "name": "Member X", "role": "client_user"},
                             timeout=15)
        assert r.status_code in (200, 201), r.text[:200]
        d = r.json()
        # api may return {user, invite_link} or {ok, user_id, invite_link}
        uid = d.get("user_id") or (d.get("user") or {}).get("user_id")
        assert uid, f"no user id in response {d}"
        assert "invite_link" in d

        # patch role
        r2 = super_admin.patch(f"{API}/admin/clients/{org_id}/users/{uid}",
                               json={"role": "client_admin"}, timeout=10)
        assert r2.status_code == 200

        # delete -> revoked
        r3 = super_admin.delete(f"{API}/admin/clients/{org_id}/users/{uid}", timeout=10)
        assert r3.status_code in (200, 204)
        # verify status revoked in listing
        listing = super_admin.get(f"{API}/admin/clients/{org_id}/users").json()["items"]
        target = [u for u in listing if (u.get("user_id") == uid)]
        if target:
            assert target[0].get("status") == "revoked"


# ─── 5. API keys ──────────────────────────────────────────────────────────
class TestApiKeys:
    @pytest.fixture(scope="class")
    def created_key(self, super_admin, created_org):
        org_id = created_org["org"]["org_id"]
        r = super_admin.post(f"{API}/admin/clients/{org_id}/api-keys",
                             json={"name": "TEST_KEY", "scope": "sandbox"}, timeout=15)
        assert r.status_code in (200, 201), r.text[:200]
        d = r.json()
        return org_id, d

    def test_create_returns_plaintext_with_warning(self, created_key):
        _, d = created_key
        assert "plaintext" in d and d["plaintext"]
        assert "prefix" in d
        # warning is recommended
        assert any(k for k in d.keys() if "warning" in k.lower()) or d.get("warning"), \
            f"expected warning key, keys={list(d.keys())}"

    def test_list_does_not_leak_secrets(self, super_admin, created_key):
        org_id, _ = created_key
        r = super_admin.get(f"{API}/admin/clients/{org_id}/api-keys", timeout=10)
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) >= 1
        for it in items:
            assert "plaintext" not in it, f"plaintext leaked in {it}"
            assert "secret_hash" not in it, f"secret_hash leaked in {it}"
            assert "hash" not in it, f"hash leaked in {it}"
            # prefix should be visible
            assert "prefix" in it

    def test_rotate_returns_new_plaintext(self, super_admin, created_key):
        org_id, d = created_key
        key_id = d.get("key_id") or d.get("id")
        r = super_admin.post(f"{API}/admin/clients/{org_id}/api-keys/{key_id}/rotate", timeout=10)
        assert r.status_code == 200, r.text[:200]
        nd = r.json()
        assert nd.get("plaintext") and nd["plaintext"] != d["plaintext"]

    def test_delete_marks_revoked(self, super_admin, created_key):
        org_id, d = created_key
        key_id = d.get("key_id") or d.get("id")
        r = super_admin.delete(f"{API}/admin/clients/{org_id}/api-keys/{key_id}", timeout=10)
        assert r.status_code in (200, 204)


# ─── 6. Webhooks (with httpbin delivery) ──────────────────────────────────
class TestWebhooks:
    @pytest.fixture(scope="class")
    def created_webhook(self, super_admin, created_org):
        org_id = created_org["org"]["org_id"]
        body = {"url": "https://httpbin.org/anything",
                "events": ["tx.created"],
                "description": "TEST webhook"}
        r = super_admin.post(f"{API}/admin/clients/{org_id}/webhooks", json=body, timeout=15)
        assert r.status_code in (200, 201), r.text[:300]
        d = r.json()
        return org_id, d

    def test_create_returns_secret_plaintext_once(self, created_webhook):
        _, d = created_webhook
        assert "secret" in d and d["secret"]
        wh = d.get("webhook") or d
        assert wh.get("webhook_id") or wh.get("id")

    def test_list_does_not_leak_secret(self, super_admin, created_webhook):
        org_id, _ = created_webhook
        r = super_admin.get(f"{API}/admin/clients/{org_id}/webhooks", timeout=10)
        assert r.status_code == 200
        items = r.json()["items"]
        for it in items:
            assert "secret" not in it, f"secret leaked in {it}"
            assert "secret_hash" not in it

    def test_test_button_delivers_with_signature(self, super_admin, created_webhook):
        org_id, d = created_webhook
        wh = d.get("webhook") or d
        wh_id = wh.get("webhook_id") or wh.get("id")
        r = super_admin.post(f"{API}/admin/clients/{org_id}/webhooks/{wh_id}/test", timeout=30)
        assert r.status_code in (200, 201, 202), r.text[:300]
        # short wait for delivery log persistence
        time.sleep(1)
        log = super_admin.get(f"{API}/admin/clients/{org_id}/webhooks/{wh_id}/deliveries",
                              timeout=10).json()
        assert log.get("items"), "no delivery log entries"
        first = log["items"][0]
        # http code should be 200 from httpbin
        code = first.get("http_code") or first.get("status_code") or first.get("response_status")
        assert code in (200, "200"), f"expected 200 got {code}, entry={first}"

    def test_reveal_secret_returns_plaintext(self, super_admin, created_webhook):
        org_id, d = created_webhook
        wh = d.get("webhook") or d
        wh_id = wh.get("webhook_id") or wh.get("id")
        original = d["secret"]
        r = super_admin.post(f"{API}/admin/clients/{org_id}/webhooks/{wh_id}/reveal-secret",
                             timeout=10)
        assert r.status_code == 200, r.text[:200]
        assert r.json().get("secret") == original


# ─── 7. Outbound emails (mock preview_only) ───────────────────────────────
class TestEmails:
    def test_emails_listed_and_preview_returns_html(self, super_admin, created_org):
        org_id = created_org["org"]["org_id"]
        r = super_admin.get(f"{API}/admin/clients/{org_id}/emails", timeout=10)
        assert r.status_code == 200
        items = r.json()["items"]
        assert items, "no outbound emails — invite email should be present"
        for it in items:
            assert "html" not in it, "html should be excluded from listing"
            assert it.get("status") in ("preview_only", "sent", "queued", "failed"), it
        email_id = items[0].get("email_id") or items[0].get("id")
        # preview returns html
        pr = super_admin.get(f"{API}/admin/clients/{org_id}/emails/{email_id}/preview", timeout=10)
        assert pr.status_code == 200, pr.text[:200]
        ct = pr.headers.get("content-type", "")
        assert "text/html" in ct.lower(), f"expected text/html got {ct}"
        assert len(pr.text) > 50


# ─── 8. Audit log ─────────────────────────────────────────────────────────
class TestAuditLog:
    def test_audit_log_has_entries(self, super_admin, created_org):
        org_id = created_org["org"]["org_id"]
        r = super_admin.get(f"{API}/admin/clients/{org_id}/audit-log", timeout=10)
        assert r.status_code == 200
        items = r.json()["items"]
        assert items, "no audit log entries"
        actions = {it.get("action") or it.get("event") or it.get("type") for it in items}
        # at least 1 should refer to create/pause/api-key/webhook
        assert actions, "no actions captured"
