"""Prosper routers package — aggregates every domain router into ALL_ROUTERS."""
from .auth import auth_router
from .dashboard import dashboard_router
from .organizations import orgs_router
from .onboarding import ob_router
from .compliance import comp_router
from .funds import funds_router, products_router
from .positions import pos_router
from .treasury import treas_router
from .transactions import tx_router
from .reconciliation import recon_router
from .integrations import int_router
from .misc import misc_router
from .end_customers import ec_router
from .users import users_router
from .admin import admin_router
from .approvals import approvals_router
from .mfa import mfa_router
from .documents import docs_router
from .search import search_router


ALL_ROUTERS = [
    auth_router, dashboard_router, orgs_router, ob_router, comp_router,
    funds_router, products_router, pos_router, treas_router, tx_router,
    recon_router, int_router, misc_router, ec_router, users_router, admin_router,
    approvals_router, mfa_router, docs_router, search_router,
]
