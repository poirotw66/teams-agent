"""Citation Asset Gateway — signed source/image delivery outside the Teams bot core.

Public HTTP contracts (`/rag-*`, `/sources/*`) stay path-stable. Adapter
channel formatting stays in ``teams_agent``; this package owns citation
viewer, signed assets, and source ACL delivery.
"""

from .source_routes import create_source_router

__all__ = ["create_source_router"]
