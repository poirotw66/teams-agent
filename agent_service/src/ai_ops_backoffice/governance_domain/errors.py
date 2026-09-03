from __future__ import annotations


class GovernanceError(Exception):
    """Base error for the Phase 3 AI governance domain."""


class GovernanceNotFoundError(GovernanceError):
    pass


class GovernanceValidationError(GovernanceError):
    pass


class GovernanceAuthorizationError(GovernanceError):
    pass


class GovernanceConflictError(GovernanceError):
    pass


class GovernanceTransitionError(GovernanceError):
    pass
