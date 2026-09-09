"""Route registrars for the agent service FastAPI app."""

from .chat import register_chat_routes
from .feedback import register_feedback_routes
from .health import register_health_routes
from .knowledge_admin import register_knowledge_admin_routes
from .ops_health import register_ops_health_routes
from .retrieval import register_retrieval_routes

__all__ = [
    "register_chat_routes",
    "register_feedback_routes",
    "register_health_routes",
    "register_knowledge_admin_routes",
    "register_ops_health_routes",
    "register_retrieval_routes",
]
