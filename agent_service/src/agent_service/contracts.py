from pydantic import BaseModel, ConfigDict, Field


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
    groups: list[str] = Field(default_factory=list)


class MessageContent(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    locale: str | None = None


class AgentRequest(StrictModel):
    requestId: str = Field(min_length=1, max_length=128)
    channel: str = Field(min_length=1, max_length=64)
    conversation: ConversationIdentity
    user: UserIdentity
    message: MessageContent


class Citation(StrictModel):
    title: str
    url: str | None = None
    chunkId: str | None = None


class AgentImage(StrictModel):
    path: str
    title: str
    altText: str
    sourceChunkId: str


class AgentResponse(StrictModel):
    answer: str
    traceId: str
    citations: list[Citation] = Field(default_factory=list)
    images: list[AgentImage] = Field(default_factory=list)


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
