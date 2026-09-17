from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationIdentity(StrictModel):
    tenantId: str | None = None
    teamId: str | None = None
    channelId: str | None = None
    conversationId: str | None = None


class UserIdentity(StrictModel):
    teamsUserId: str | None = None
    entraObjectId: str | None = None
    displayName: str | None = None
    email: str | None = None
    groups: list[str] = Field(default_factory=list)


class MessageContent(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    locale: str | None = None


EVALUATION_EVIDENCE_CHANNEL = "__golden_evaluation__"


class AgentRequest(StrictModel):
    requestId: str = Field(min_length=1, max_length=128)
    channel: str = Field(min_length=1, max_length=64)
    conversation: ConversationIdentity
    user: UserIdentity
    message: MessageContent
    correlationId: str | None = None
    evaluationKnowledgeBackend: Literal["HYBRID", "GEMINI_FILE_SEARCH"] | None = None


class RetrievalCandidate(StrictModel):
    rank: int = Field(ge=1)
    chunkId: str
    documentId: str | None = None
    canonicalSourceId: str | None = None
    title: str
    score: float | None = None
    sparseScore: float | None = None
    denseScore: float | None = None
    scoreOrigin: Literal["HYBRID", "PROVIDER_UNAVAILABLE"]
    selectedForContext: bool = False
    rejectionReason: str | None = None


class RetrievalAttempt(StrictModel):
    searchQuery: str
    candidates: list[RetrievalCandidate] = Field(default_factory=list)
    decision: str | None = None
    isRelevant: bool | None = None
    rewriteQuery: str | None = None


class GroundedClaim(StrictModel):
    text: str
    chunkIds: list[str] = Field(min_length=1)


class PolicyAdvisory(StrictModel):
    """System security policy overlay, distinct from document-grounded claims."""

    text: str
    policyIds: list[str] = Field(min_length=1)


class RetrievalTrace(StrictModel):
    rawUserUtterance: str
    resolvedIssueQuery: str
    searchQuery: str
    facetQueries: list[str] = Field(default_factory=list, max_length=3)
    selectedBackend: str
    actualBackend: str
    attempts: list[RetrievalAttempt] = Field(default_factory=list)
    selectedChunkIds: list[str] = Field(default_factory=list)
    answerability: Literal["FULL", "PARTIAL", "NONE"] | None = None
    claims: list[GroundedClaim] = Field(default_factory=list)
    policyAdvisories: list[PolicyAdvisory] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    fallbackPath: str
    terminalReason: str | None = None


class Citation(StrictModel):
    title: str
    url: str | None = None
    chunkId: str | None = None
    # Stable source identity.  These fields are optional so FAQ/ticket
    # citations and older adapters remain backward compatible.
    sourceRefId: str | None = None
    canonicalSourceId: str | None = None
    sourceAliases: list[str] = Field(default_factory=list)
    documentId: str | None = None
    versionId: str | None = None
    releaseId: str | None = None
    sourcePath: str | None = None
    section: str | None = None
    page: int | None = Field(default=None, ge=1)
    evidence: str | None = None
    sourceType: str | None = None
    originalAssetAvailable: bool = False
    originalAssetName: str | None = None


class AgentImage(StrictModel):
    path: str
    title: str
    altText: str
    sourceChunkId: str
    releaseId: str | None = None


# --- Issue domain model (spec §4.3, §6) -----------------------------------

# Readiness: whether an issue has enough information to be routed.
Readiness = Literal["READY", "NEED_MORE_INFO", "NOT_IT", "GREETING"]

# Route: the high-level handling path chosen by the Issue Extractor.
Route = Literal["FAQ", "KNOWLEDGE", "TICKET", "NOT_IT", "GREETING"]

# IssueResultType: outcome of processing a single issue (spec §4.3).
IssueResultType = Literal[
    "FAQ_ANSWERED",
    "KNOWLEDGE_ANSWERED",
    "NO_KNOWLEDGE",
    "NEED_MORE_INFO",
    "TICKET_CREATED",
    "TICKET_FOUND",
    "TICKET_CANCELLED",
    "TICKET_DELETE_DENIED",
    "FAILED",
]

# Per spec §6.3, at most two missing-info questions may be asked per issue.
_MAX_MISSING_INFO = 2


class Issue(StrictModel):
    id: int
    description: str
    isIT: bool
    readiness: Readiness
    missingInfo: list[str] = Field(default_factory=list)
    route: Route
    faqKey: str | None = None
    ticketAction: str | None = None
    # Optional extractor/taxonomy id. When present, ops classification prefers
    # MODEL over keyword rules (FAQ mapping still wins).
    issueTypeId: str | None = None

    @field_validator("missingInfo")
    @classmethod
    def _cap_missing_info(cls, value: list[str]) -> list[str]:
        # Spec §6.3: at most two missing-info questions per issue. Truncate
        # rather than reject so a slightly over-eager LLM output is still usable.
        return value[:_MAX_MISSING_INFO]


class IssueExtraction(StrictModel):
    """Pydantic schema the Issue Extractor's structured LLM output binds to."""

    issues: list[Issue] = Field(default_factory=list)


class IssueResult(StrictModel):
    issueId: int
    resultType: IssueResultType
    answer: str = ""
    sources: list[Citation] = Field(default_factory=list)
    images: list[AgentImage] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    ticketId: str | None = None
    backend: str | None = None
    error: str | None = None
    faqId: str | None = None
    faqKey: str | None = None
    faqVersionId: str | None = None
    terminalReason: str | None = None
    retrievalTrace: RetrievalTrace | None = Field(default=None, exclude=True)
    answerability: Literal["FULL", "PARTIAL", "NONE"] | None = Field(
        default=None,
        exclude=True,
    )
    claims: list[GroundedClaim] = Field(default_factory=list, exclude=True)
    policyAdvisories: list[PolicyAdvisory] = Field(default_factory=list, exclude=True)
    unknowns: list[str] = Field(default_factory=list, exclude=True)


class AgentResponse(StrictModel):
    answer: str
    traceId: str
    citations: list[Citation] = Field(default_factory=list)
    images: list[AgentImage] = Field(default_factory=list)
    correlationId: str | None = None
    issueResults: list[IssueResult] = Field(default_factory=list)
    feedbackEnabled: bool = False
    estimatedCostUsd: float | None = None
    estimatedCostTwd: float | None = None
    costComplete: bool | None = None


class IssueRetrievalTrace(StrictModel):
    issueId: int
    trace: RetrievalTrace


class AgentEvaluationResponse(AgentResponse):
    retrievalTraces: list[IssueRetrievalTrace] = Field(default_factory=list)
    llmCallCount: int = Field(default=0, ge=0)


# --- User / conversation context (spec §10, §11.4, §12) -------------------


class UserContext(StrictModel):
    teamsUserId: str | None = None
    entraObjectId: str | None = None
    displayName: str | None = None
    email: str | None = None
    groups: list[str] = Field(default_factory=list)

    @property
    def is_trusted_for_ticket(self) -> bool:
        """True only when a stable id, display name and email are all present.

        Spec §11.4: requesterId/name/email for a ticket must come from a
        trustworthy Teams/Entra context, never from free-text user input.
        """
        stable_id = self.entraObjectId or self.teamsUserId
        return bool(stable_id and self.displayName and self.email)


class PendingIssueContext(StrictModel):
    """Structured unresolved issue state carried between conversation turns."""

    description: str
    # The user's original wording is kept separately from the extractor's
    # normalized description.  It lets a later short fragment (for example
    # "Webex" or "會議借用") be composed into a clean retrieval query without
    # depending on model-generated prose.
    contextText: str | None = None
    route: Route = "KNOWLEDGE"
    faqKey: str | None = None
    missingInfo: list[str] = Field(default_factory=list)
    askedQuestions: list[str] = Field(default_factory=list)
    clarificationCount: int = Field(default=0, ge=0)


class ConversationMessage(StrictModel):
    role: Literal["user", "assistant"]
    text: str
    createdAt: datetime
    requestId: str | None = None
    correlationId: str | None = None
    followUpState: Literal["NONE", "AWAITING_CLARIFICATION", "AWAITING_TICKET_CONFIRMATION"] = (
        "NONE"
    )
    pendingIssues: list[PendingIssueContext] = Field(default_factory=list)


class ConversationContext(StrictModel):
    conversationId: str
    startedAt: datetime
    lastActivityAt: datetime
    messages: list[ConversationMessage] = Field(default_factory=list)


# --- Knowledge Service (spec §8.1) -----------------------------------------

# Source / SourceImage are aliases for the existing Citation / AgentImage
# models rather than duplicate types, per the spec's Knowledge Service
# interface naming (§8.1).
Source = Citation
SourceImage = AgentImage


class KnowledgeResult(StrictModel):
    found: bool
    answer: str
    sources: list[Citation] = Field(default_factory=list)
    images: list[AgentImage] = Field(default_factory=list)
    backend: str
    terminalReason: str | None = None
    retrievalTrace: RetrievalTrace | None = Field(default=None, exclude=True)
    answerability: Literal["FULL", "PARTIAL", "NONE"] | None = Field(
        default=None,
        exclude=True,
    )
    claims: list[GroundedClaim] = Field(default_factory=list, exclude=True)
    policyAdvisories: list[PolicyAdvisory] = Field(default_factory=list, exclude=True)
    unknowns: list[str] = Field(default_factory=list, exclude=True)


# --- FAQ (spec §7.2) ---------------------------------------------------


class FaqEntry(StrictModel):
    id: str
    faqKey: str
    enabled: bool = True
    answer: str
    versionId: str | None = None


# --- Ticket Service (spec §11) ------------------------------------------


class TicketItem(StrictModel):
    id: str
    name: str
    level: int = Field(default=1, ge=1)
    path: list[str] = Field(default_factory=list)


class Ticket(StrictModel):
    id: str
    title: str
    status: str
    createdAt: datetime | None = None
    url: str | None = None


class TicketDraft(StrictModel):
    requesterId: str
    requesterName: str
    requesterEmail: str
    title: str
    description: str
    ticketItemId: str
    priority: str = "NORMAL"


# --- Feedback (spec §14) -------------------------------------------------


class FeedbackRequest(StrictModel):
    correlationId: str
    conversationId: str | None = None
    issueId: int | None = None
    rating: Literal["UP", "DOWN"]
    userId: str | None = None
    reason: str | None = None
    resolvedStatus: Literal["YES", "NO", "UNKNOWN"] | None = None


class SearchRequest(StrictModel):
    query: str = Field(min_length=1, max_length=1000)
    tenantId: str | None = None
    groups: list[str] = Field(default_factory=list)
    limit: int = Field(default=4, ge=1, le=20)


class SearchHit(StrictModel):
    chunkId: str
    title: str
    sourcePath: str
    content: str
    score: float


class SearchResponse(StrictModel):
    hits: list[SearchHit]


class KnowledgeBackendUpdate(StrictModel):
    backend: Literal["HYBRID", "GEMINI_FILE_SEARCH"]


class ReloadKnowledgeRequest(StrictModel):
    releaseId: str | None = None
    release_id: str | None = None
    reason: str | None = None

    @property
    def target_release_id(self) -> str | None:
        return self.releaseId or self.release_id
