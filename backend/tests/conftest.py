import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://finance-control-215.preview.emergentagent.com").rstrip("/")
TOKEN = os.environ.get("PROSPER_TEST_TOKEN", "test_session_prosper_super_admin")
CLIENT_TOKEN = os.environ.get("PROSPER_CLIENT_TOKEN", "test_session_prosper_client_admin")


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def auth_client():
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TOKEN}",
    })
    return s


@pytest.fixture(scope="session")
def client_auth_client():
    """Session authenticated as a non-internal client_admin for scope-guard tests."""
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CLIENT_TOKEN}",
    })
    return s
