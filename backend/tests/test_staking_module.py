"""Backend tests for the /admin/staking module (P1-3 Feb 2026)."""
import os
import pytest
import requests

BASE_URL = os.environ.get(
    "TEST_BASE_URL",
    "https://finance-control-215.preview.emergentagent.com").rstrip("/")

ADMIN_EMAIL = "admin@prosper.foundation"


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.get(f"{BASE_URL}/api/v1/auth/dev-login",
              params={"email": ADMIN_EMAIL, "next": "/admin/staking"},
              allow_redirects=False, timeout=30)
    assert r.status_code in (302, 303, 307), f"dev-login {r.status_code} {r.text[:200]}"
    # Verify session cookie set
    assert any(c for c in s.cookies), "no session cookie set"
    return s


@pytest.fixture(scope="module")
def anon_session():
    return requests.Session()


class TestAuthGating:
    def test_wallets_requires_auth(self, anon_session):
        r = anon_session.get(f"{BASE_URL}/api/v1/admin/prosper/cms/wallets",
                             timeout=15)
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}"

    def test_cashin_requires_auth(self, anon_session):
        r = anon_session.post(f"{BASE_URL}/api/v1/admin/prosper/cms/cashin",
                              json={"prosper_id": "x@y.com", "modality": "end"},
                              timeout=15)
        assert r.status_code in (401, 403)


class TestTreasury:
    def test_treasury_ok(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/v1/admin/prosper/treasury",
                              timeout=45)
        # allow one retry on 502 (CMS flakiness)
        if r.status_code == 502:
            r = admin_session.get(f"{BASE_URL}/api/v1/admin/prosper/treasury",
                                  timeout=45)
        assert r.status_code == 200, f"treasury {r.status_code} {r.text[:200]}"
        d = r.json()
        assert "balanceUSDC" in d and "balanceARSA" in d and "balanceXLM" in d
        assert d.get("mode") is not None


class TestCmsWallets:
    def test_wallets_list(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/v1/admin/prosper/cms/wallets",
                              timeout=45)
        if r.status_code == 502:
            r = admin_session.get(f"{BASE_URL}/api/v1/admin/prosper/cms/wallets",
                                  timeout=45)
        assert r.status_code == 200, f"wallets {r.status_code} {r.text[:300]}"
        d = r.json()
        assert "items" in d and "total" in d and "mode" in d and "fetched_at" in d
        assert isinstance(d["items"], list)
        # our seeded QA user should be present
        emails = [str(x.get("email") or "").lower() for x in d["items"]]
        assert any("qa-staking-module@prosper.foundation" in e for e in emails), \
            f"seeded qa-staking-module email not in wallets: {emails[:5]}"

    def test_wallets_seeded_row_has_address(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/v1/admin/prosper/cms/wallets",
                              timeout=45)
        assert r.status_code == 200
        target = next((x for x in r.json()["items"]
                       if str(x.get("email") or "").lower()
                       == "qa-staking-module@prosper.foundation"), None)
        assert target is not None
        assert target.get("address"), f"seeded wallet has no address: {target}"


class TestCmsCashin:
    def test_cashin_idempotent_reused(self, admin_session):
        body = {"prosper_id": "qa-staking-module@prosper.foundation",
                "modality": "end"}
        r = admin_session.post(f"{BASE_URL}/api/v1/admin/prosper/cms/cashin",
                               json=body, timeout=60)
        if r.status_code == 502:
            r = admin_session.post(f"{BASE_URL}/api/v1/admin/prosper/cms/cashin",
                                   json=body, timeout=60)
        assert r.status_code == 200, f"cashin {r.status_code} {r.text[:300]}"
        d = r.json()
        assert d["prosper_id"] == body["prosper_id"]
        assert d["modality"] == "end"
        assert d.get("address"), f"no address returned: {d}"
        # Idempotent - must be reused
        assert d.get("reused") is True, \
            f"expected reused=True for seeded QA user, got: {d}"

    def test_cashin_invalid_modality_422(self, admin_session):
        r = admin_session.post(f"{BASE_URL}/api/v1/admin/prosper/cms/cashin",
                               json={"prosper_id": "x@y.com",
                                     "modality": "bogus"},
                               timeout=20)
        assert r.status_code == 422

    def test_cashin_missing_prosper_id_422(self, admin_session):
        r = admin_session.post(f"{BASE_URL}/api/v1/admin/prosper/cms/cashin",
                               json={"modality": "end"}, timeout=20)
        assert r.status_code == 422

    # ---- P1-5: email+asset flow (Jan 2026) ----

    def test_cashin_email_asset_usdc_ok(self, admin_session):
        """New body shape: {email, modality, asset} → 200 with asset echoed."""
        body = {"email": "qa-staking-module@prosper.foundation",
                "modality": "end", "asset": "usdc"}
        r = admin_session.post(f"{BASE_URL}/api/v1/admin/prosper/cms/cashin",
                               json=body, timeout=60)
        if r.status_code == 502:
            r = admin_session.post(f"{BASE_URL}/api/v1/admin/prosper/cms/cashin",
                                   json=body, timeout=60)
        assert r.status_code == 200, f"cashin {r.status_code} {r.text[:300]}"
        d = r.json()
        assert d.get("email") == body["email"] or d.get("prosper_id") == body["email"]
        assert d.get("modality") == "end"
        assert d.get("asset") == "usdc", f"asset not echoed: {d}"
        assert d.get("address"), f"no address: {d}"
        assert d.get("reused") is True

    def test_cashin_email_asset_arsa_ok(self, admin_session):
        body = {"email": "qa-staking-module@prosper.foundation",
                "modality": "end", "asset": "arsa"}
        r = admin_session.post(f"{BASE_URL}/api/v1/admin/prosper/cms/cashin",
                               json=body, timeout=60)
        if r.status_code == 502:
            r = admin_session.post(f"{BASE_URL}/api/v1/admin/prosper/cms/cashin",
                                   json=body, timeout=60)
        assert r.status_code == 200, f"cashin {r.status_code} {r.text[:300]}"
        d = r.json()
        assert d.get("asset") == "arsa"

    def test_cashin_missing_email_and_prosper_id_422(self, admin_session):
        r = admin_session.post(f"{BASE_URL}/api/v1/admin/prosper/cms/cashin",
                               json={"modality": "end", "asset": "usdc"},
                               timeout=20)
        assert r.status_code == 422, f"expected 422 got {r.status_code} {r.text[:200]}"

    def test_cashin_invalid_asset_422(self, admin_session):
        r = admin_session.post(f"{BASE_URL}/api/v1/admin/prosper/cms/cashin",
                               json={"email": "qa-staking-module@prosper.foundation",
                                     "modality": "end", "asset": "btc"},
                               timeout=20)
        assert r.status_code == 422, f"expected 422 got {r.status_code} {r.text[:200]}"

    def test_cashin_legacy_prosper_id_still_works(self, admin_session):
        """Compat: legacy body {prosper_id, modality} without asset still 200."""
        body = {"prosper_id": "qa-staking-module@prosper.foundation",
                "modality": "end"}
        r = admin_session.post(f"{BASE_URL}/api/v1/admin/prosper/cms/cashin",
                               json=body, timeout=60)
        if r.status_code == 502:
            r = admin_session.post(f"{BASE_URL}/api/v1/admin/prosper/cms/cashin",
                                   json=body, timeout=60)
        assert r.status_code == 200, f"legacy {r.status_code} {r.text[:300]}"
        d = r.json()
        assert d.get("address")
        assert d.get("reused") is True


class TestStakingSync:
    def test_sync_status(self, admin_session):
        r = admin_session.get(
            f"{BASE_URL}/api/v1/admin/prosper/staking-sync/status", timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert "enabled" in d and "mode" in d and "interval_minutes" in d

    def test_sync_run(self, admin_session):
        r = admin_session.post(
            f"{BASE_URL}/api/v1/admin/prosper/staking-sync/run", timeout=120)
        assert r.status_code == 200, f"sync run {r.status_code} {r.text[:300]}"
        d = r.json()
        # Must include the summary keys the UI displays
        assert "processed" in d or "ok" in d


class TestStakingsList:
    def test_stakings_all(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/v1/admin/prosper/stakings",
                              params={"scope": "all"}, timeout=45)
        assert r.status_code == 200
        d = r.json()
        assert "ours" in d and "external" in d and "total" in d
        assert isinstance(d["ours"]["items"], list)

    def test_stakings_filter_asset(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/v1/admin/prosper/stakings",
                              params={"scope": "all", "asset": "usdc"},
                              timeout=45)
        assert r.status_code == 200

    def test_stakings_invalid_filter_422(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/v1/admin/prosper/stakings",
                              params={"asset": "bogus"}, timeout=20)
        assert r.status_code == 422


class TestCmsCreateUser:
    """P1-4 · POST /cms/users — CMS account creation without wallet."""

    def test_create_user_requires_auth(self, anon_session):
        r = anon_session.post(
            f"{BASE_URL}/api/v1/admin/prosper/cms/users",
            json={"email": "someone@example.com"}, timeout=15)
        assert r.status_code in (401, 403), \
            f"expected 401/403, got {r.status_code}"

    def test_create_user_missing_email_422(self, admin_session):
        r = admin_session.post(
            f"{BASE_URL}/api/v1/admin/prosper/cms/users",
            json={}, timeout=20)
        assert r.status_code == 422, \
            f"expected 422 for missing email, got {r.status_code} {r.text[:200]}"

    def test_create_user_duplicate_409(self, admin_session):
        # qa-cuenta-nueva@prosper.foundation was already created by main agent
        body = {"email": "qa-cuenta-nueva@prosper.foundation"}
        r = admin_session.post(
            f"{BASE_URL}/api/v1/admin/prosper/cms/users",
            json=body, timeout=45)
        if r.status_code == 502:
            r = admin_session.post(
                f"{BASE_URL}/api/v1/admin/prosper/cms/users",
                json=body, timeout=45)
        assert r.status_code == 409, \
            f"expected 409 duplicate, got {r.status_code} {r.text[:200]}"


class TestStakingsRichFields:
    """P1-6 · GET /stakings must expose all detail fields for the admin UI."""

    def test_stakings_items_have_new_fields(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/v1/admin/prosper/stakings",
                              params={"scope": "all"}, timeout=60)
        if r.status_code == 502:
            r = admin_session.get(f"{BASE_URL}/api/v1/admin/prosper/stakings",
                                  params={"scope": "all"}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        all_items = list(d["ours"]["items"]) + list(d["external"]["items"])
        assert len(all_items) > 0, "no stakings returned"
        # Every item must at least expose these keys (values may be None)
        # Baseline keys that must always be present.
        required = {"asset", "modality", "status", "principal_native",
                    "wallet", "start", "maturity", "rate"}
        for it in all_items:
            missing = required - set(it.keys())
            assert not missing, f"item missing keys {missing}: {it}"
        # At least one 'ours' item must have contract_email + rate + maturity
        # populated by the sync from the CMS.
        ours = d["ours"]["items"]
        if ours:
            enriched = [x for x in ours
                        if x.get("contract_email") and x.get("rate") is not None
                        and x.get("maturity")]
            assert enriched, \
                f"no 'ours' staking has contract_email+rate+maturity: {ours[:2]}"
            # projected_interest / daily_interest / next_payout should be
            # populated for at least one row after the sync.
            has_proj = any(x.get("projected_interest") is not None for x in ours)
            has_daily = any(x.get("daily_interest") is not None for x in ours)
            has_next = any(x.get("next_payout") is not None for x in ours)
            assert has_proj, f"no 'ours' item has projected_interest: {[x.get('position_id') for x in ours]}"
            assert has_daily, "no 'ours' item has daily_interest"
            assert has_next, "no 'ours' item has next_payout"

    def test_stakings_by_org_summary_present(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/v1/admin/prosper/stakings",
                              params={"scope": "all"}, timeout=45)
        if r.status_code == 502:
            r = admin_session.get(f"{BASE_URL}/api/v1/admin/prosper/stakings",
                                  params={"scope": "all"}, timeout=45)
        assert r.status_code == 200
        d = r.json()
        by_org = d["ours"].get("by_org")
        assert isinstance(by_org, list), f"by_org missing/not list: {by_org}"
        if by_org:
            g = by_org[0]
            for k in ("org_id", "name", "principal_arsa", "principal_usdc",
                      "active_count"):
                assert k in g, f"by_org row missing {k}: {g}"


class TestRegressionInversiones:
    def test_treasury_regression(self, admin_session):
        # The /admin/prosper/inversiones page consumes /treasury.
        r = admin_session.get(f"{BASE_URL}/api/v1/admin/prosper/treasury",
                              timeout=45)
        if r.status_code == 502:
            r = admin_session.get(f"{BASE_URL}/api/v1/admin/prosper/treasury",
                                  timeout=45)
        assert r.status_code == 200
