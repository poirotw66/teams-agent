"""Conversation Repository & Service (spec §3.2, §10, §18.4).

Public facade: import from ``agent_service.conversation``.
Implementations live in sibling modules under this package.
"""

from .factory import build_repository
from .file_store import FileConversationRepository
from .firestore_store import FirestoreConversationRepository
from .helpers import ConversationRepository, _conversation_key, _utc_now
from .memory import InMemoryConversationRepository
from .service import ConversationService

__all__ = [
    "ConversationRepository",
    "ConversationService",
    "FileConversationRepository",
    "FirestoreConversationRepository",
    "InMemoryConversationRepository",
    "build_repository",
    "_conversation_key",
    "_utc_now",
]
