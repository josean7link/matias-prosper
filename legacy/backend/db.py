"""MongoDB connection and collection accessors for Prosper platform."""
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]


def col(name: str):
    return db[name]


# Collection names (source of truth)
USERS = "prosper_users"
SESSIONS = "prosper_sessions"
ORGANIZATIONS = "prosper_organizations"
ORG_USERS = "prosper_org_users"
ROLES = "prosper_roles"
ONBOARDING = "prosper_onboarding_cases"
COMPLIANCE = "prosper_compliance_reviews"
DOCUMENTS = "prosper_documents"
FUNDS = "prosper_funds"
PRODUCTS = "prosper_products"
NAV_SNAPSHOTS = "prosper_nav_snapshots"
WALLETS = "prosper_wallets"
TREASURY = "prosper_treasury_accounts"
POSITIONS = "prosper_positions"
PAYOUT_SCHEDULES = "prosper_payout_schedules"
TRANSACTIONS = "prosper_transactions"
BLOCKCHAIN_EVENTS = "prosper_blockchain_events"
RECONCILIATION = "prosper_reconciliation_records"
API_APPS = "prosper_api_apps"
API_KEYS = "prosper_api_keys"
WEBHOOK_ENDPOINTS = "prosper_webhook_endpoints"
WEBHOOK_DELIVERIES = "prosper_webhook_deliveries"
ALERTS = "prosper_alerts"
TASKS = "prosper_tasks"
REPORTS = "prosper_reports"
AUDIT_LOGS = "prosper_audit_logs"
END_CUSTOMERS = "prosper_end_customers"
APPROVALS = "prosper_approvals"
IDEMPOTENCY = "prosper_idempotency_keys"
