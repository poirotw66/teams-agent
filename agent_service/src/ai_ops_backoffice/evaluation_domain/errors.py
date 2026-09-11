from __future__ import annotations


class EvaluationDomainError(Exception):
    """Base error for the evaluation domain."""


class EvaluationNotFoundError(EvaluationDomainError):
    """Raised when an evaluation entity cannot be found."""


class EvaluationValidationError(EvaluationDomainError):
    """Raised when input validation fails."""


class EvaluationAuthorizationError(EvaluationDomainError):
    """Raised when an actor lacks permission or violates separation of duties."""


class EvaluationVersionConflictError(EvaluationDomainError):
    """Raised on concurrent etag or version conflicts."""


class EvaluationIdempotencyConflictError(EvaluationDomainError):
    """Raised when an idempotency key is reused with different arguments."""


class EvaluationTransitionError(EvaluationDomainError):
    """Raised when a state machine transition is invalid."""


class EvaluationAuditWriteError(EvaluationDomainError):
    """Raised when an audit record cannot be written."""


class JobLeaseLostError(EvaluationDomainError):
    """Raised when a worker attempts to update a job whose lease has expired or been claimed by another worker."""


class JobFencingConflictError(EvaluationDomainError):
    """Raised when a worker's fencing token is outdated compared to the job's current fencing token."""

