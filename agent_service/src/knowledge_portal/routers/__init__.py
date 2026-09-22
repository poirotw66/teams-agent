"""Knowledge Portal HTTP route modules."""

from __future__ import annotations

from .admin_routes import register_admin_routes
from .catalog_routes import register_catalog_routes
from .documents_assets_routes import register_documents_assets_routes
from .documents_import_routes import register_documents_import_routes
from .documents_routes import register_documents_routes
from .health_routes import register_health_routes
from .releases_routes import register_releases_routes
from .reviews_routes import register_reviews_routes
from .tests_routes import register_tests_routes

__all__ = [
    "register_admin_routes",
    "register_catalog_routes",
    "register_documents_assets_routes",
    "register_documents_import_routes",
    "register_documents_routes",
    "register_health_routes",
    "register_releases_routes",
    "register_reviews_routes",
    "register_tests_routes",
]
