from __future__ import annotations


class FaqDomainError(Exception):
    """Base error for the isolated FAQ governance domain."""


class FaqNotFoundError(FaqDomainError):
    pass


class FaqValidationError(FaqDomainError):
    pass


class FaqAuthorizationError(FaqDomainError):
    pass


class FaqVersionConflictError(FaqDomainError):
    pass


class FaqIdempotencyConflictError(FaqDomainError):
    pass


class FaqTransitionError(FaqDomainError):
    pass
