"""Tests for the new /api/documents endpoints (KYC/KYB Emergent Object Storage)."""
import io
import os
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://finance-control-215.preview.emergentagent.com").rstrip("/")
TOKEN = os.environ.get("PROSPER_TEST_TOKEN", "test_session_prosper_super_admin")
CLIENT_TOKEN = os.environ.get("PROSPER_CLIENT_TOKEN", "test_session_prosper_client_admin")
HDR = {"Authorization": f"Bearer {TOKEN}"}
CLIENT_HDR = {"Authorization": f"Bearer {CLIENT_TOKEN}"}

# Tiny valid PDF (header bytes)
PDF_BYTES = (
    b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\n"
    b"trailer<<>>\n%%EOF\n"
)

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000000000200015c8d2c870000000049454e44ae426082"
)


@pytest.fixture(scope="module")
def org_id():
    r = requests.get(f"{BASE}/api/organizations", headers=HDR, timeout=20)
    assert r.status_code == 200, f"orgs: {r.status_code} {r.text[:300]}"
    items = r.json().get("items", [])
    assert items, "no orgs returned"
    # Prefer the dev-test org if present
    for o in items:
        if o.get("org_id") == "org_e0d081eab53d":
            return o["org_id"]
    return items[0]["org_id"]


@pytest.fixture(scope="module")
def uploaded_doc(org_id):
    files = {"file": ("test_doc.pdf", io.BytesIO(PDF_BYTES), "application/pdf")}
    data = {"org_id": org_id, "doc_type": "kyc"}
    r = requests.post(f"{BASE}/api/documents/upload", files=files, data=data, headers=HDR, timeout=60)
    assert r.status_code == 200, f"upload failed {r.status_code}: {r.text[:400]}"
    body = r.json()
    assert body["document_id"].startswith("doc_")
    assert body["org_id"] == org_id
    assert body["doc_type"] == "kyc"
    assert body["original_filename"] == "test_doc.pdf"
    assert body["storage_path"]
    assert body["size"] == len(PDF_BYTES)
    assert body.get("is_deleted") is False
    return body


def test_upload_returns_document_record(uploaded_doc):
    assert uploaded_doc["content_type"] in ("application/pdf",)


def test_list_documents_includes_uploaded(uploaded_doc, org_id):
    r = requests.get(f"{BASE}/api/documents", params={"org_id": org_id}, headers=HDR, timeout=20)
    assert r.status_code == 200
    items = r.json().get("items", [])
    ids = [d["document_id"] for d in items]
    assert uploaded_doc["document_id"] in ids
    assert all(not d.get("is_deleted") for d in items)


def test_download_document_returns_bytes(uploaded_doc):
    r = requests.get(
        f"{BASE}/api/documents/{uploaded_doc['document_id']}/download",
        headers=HDR, timeout=30,
    )
    assert r.status_code == 200, f"download {r.status_code}: {r.text[:300]}"
    assert r.headers.get("Content-Type", "").startswith("application/pdf")
    assert r.content.startswith(b"%PDF")
    # Original bytes must be preserved
    assert r.content == PDF_BYTES


def test_upload_disallowed_extension():
    files = {"file": ("malware.exe", io.BytesIO(b"MZ\x90\x00"), "application/octet-stream")}
    data = {"org_id": "org_e0d081eab53d", "doc_type": "other"}
    r = requests.post(f"{BASE}/api/documents/upload", files=files, data=data, headers=HDR, timeout=20)
    assert r.status_code == 400
    assert "not allowed" in r.text.lower()


def test_upload_disallowed_zip():
    files = {"file": ("bundle.zip", io.BytesIO(b"PK\x03\x04"), "application/zip")}
    data = {"org_id": "org_e0d081eab53d", "doc_type": "other"}
    r = requests.post(f"{BASE}/api/documents/upload", files=files, data=data, headers=HDR, timeout=20)
    assert r.status_code == 400
    assert ".zip" in r.text.lower() or "not allowed" in r.text.lower()


def test_upload_png_works(org_id):
    files = {"file": ("logo.png", io.BytesIO(PNG_BYTES), "image/png")}
    data = {"org_id": org_id, "doc_type": "other"}
    r = requests.post(f"{BASE}/api/documents/upload", files=files, data=data, headers=HDR, timeout=30)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["content_type"] == "image/png"
    # cleanup
    requests.delete(f"{BASE}/api/documents/{body['document_id']}", headers=HDR, timeout=20)


def test_delete_soft_removes(uploaded_doc, org_id):
    r = requests.delete(f"{BASE}/api/documents/{uploaded_doc['document_id']}", headers=HDR, timeout=20)
    assert r.status_code == 200
    # subsequent list should NOT contain it
    r2 = requests.get(f"{BASE}/api/documents", params={"org_id": org_id}, headers=HDR, timeout=20)
    ids = [d["document_id"] for d in r2.json().get("items", [])]
    assert uploaded_doc["document_id"] not in ids
    # download should now 404
    r3 = requests.get(f"{BASE}/api/documents/{uploaded_doc['document_id']}/download", headers=HDR, timeout=20)
    assert r3.status_code == 404


def test_unauthenticated_upload_rejected():
    files = {"file": ("x.pdf", io.BytesIO(PDF_BYTES), "application/pdf")}
    data = {"org_id": "org_e0d081eab53d", "doc_type": "kyc"}
    r = requests.post(f"{BASE}/api/documents/upload", files=files, data=data, timeout=20)
    assert r.status_code in (401, 403)


def test_client_admin_cannot_upload_to_other_org():
    """Cross-org upload guard — non-internal user must be blocked with 403."""
    # Find any org that is NOT the client's own (Alemany Capital)
    r = requests.get(f"{BASE}/api/organizations", headers=HDR, timeout=15)
    assert r.status_code == 200
    others = [o["org_id"] for o in r.json().get("items", []) if o.get("name") != "Alemany Capital"]
    assert others, "no non-Alemany org seeded"
    other_org = others[0]

    files = {"file": ("crossorg.pdf", io.BytesIO(PDF_BYTES), "application/pdf")}
    data = {"org_id": other_org, "doc_type": "kyb"}
    r2 = requests.post(f"{BASE}/api/documents/upload", files=files, data=data, headers=CLIENT_HDR, timeout=30)
    assert r2.status_code == 403, f"expected 403 got {r2.status_code}: {r2.text[:200]}"


def test_client_admin_can_upload_to_own_org():
    """Client admin must still be allowed to upload to their own org (happy path)."""
    files = {"file": ("own_org.pdf", io.BytesIO(PDF_BYTES), "application/pdf")}
    # Do NOT pass org_id — endpoint should default to the caller's own org
    data = {"doc_type": "kyc"}
    r = requests.post(f"{BASE}/api/documents/upload", files=files, data=data, headers=CLIENT_HDR, timeout=30)
    assert r.status_code == 200, f"own-org upload failed {r.status_code}: {r.text[:300]}"
    body = r.json()
    assert body["uploaded_by_email"] == "demo.client@alemany.capital"
    # cleanup
    requests.delete(f"{BASE}/api/documents/{body['document_id']}", headers=CLIENT_HDR, timeout=15)


# Smoke regression: previously working endpoints still respond
def test_smoke_auth_me():
    r = requests.get(f"{BASE}/api/auth/me", headers=HDR, timeout=15)
    assert r.status_code == 200
    assert r.json().get("email") == "demo.admin@prosper.foundation"


def test_smoke_orgs_list():
    r = requests.get(f"{BASE}/api/organizations", headers=HDR, timeout=15)
    assert r.status_code == 200 and r.json().get("total", 0) >= 1


def test_smoke_dashboard():
    r = requests.get(f"{BASE}/api/dashboard/overview", headers=HDR, timeout=20)
    assert r.status_code == 200
    assert "kpis" in r.json()
