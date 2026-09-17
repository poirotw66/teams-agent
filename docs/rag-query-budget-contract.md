# RAG Query and Budget Contract

This contract separates conversation evidence from retrieval inputs so a short
follow-up cannot replace the resolved issue.

## Query layers

1. `raw_user_utterance`
   - The latest user message.
   - Used for audit and conversation interpretation.
   - Never replaces a resolved issue or becomes the sole answer-generation
     question after clarification.
2. `resolved_issue_query`
   - The immutable, complete issue produced after issue extraction and
     multi-turn clarification merging.
   - Controls overall relevance, answerability, applicability, and answer
     generation.
3. `search_query`
   - The mutable retrieval expression.
   - Starts as `resolved_issue_query` and may be rewritten once.
   - Product names, identifiers, error codes, requested facets, and negative
     constraints must be preserved.
4. `facet_queries`
   - Up to three bounded retrieval expressions for distinct required facets
     within one resolved issue.
   - They do not split independent issues; `IssueExtractor` owns that boundary.
   - They permit at most one reretrieve cycle and fall back to `search_query`
     when request budget is insufficient.

Relevance requires both positive facet support and compatibility with the
constraints in `resolved_issue_query`. Retrieval score alone does not establish
answerability.

## Clarification probe

A `NEED_MORE_INFO` issue may run an ACL-filtered retrieval probe. It may answer
without clarification only when:

- the system or entity is unique;
- the requested facet is identifiable;
- candidate applicability does not conflict;
- every required field has supporting evidence.

Otherwise, probe evidence may only make the clarification more precise.

## Request budget

- Default request deadline: 30 seconds.
- Default shared model-call budget: 6 calls.
- Maximum facet queries: 3.
- Maximum reretrieve cycles: 1.
- Simple FAQ or single-source answers must not add a separate planning call.
- Structured planning and rendering use one model invocation.
- Facet expansion and reranking must degrade to a single query before exceeding
  the request deadline or model-call budget.

The shared `ExecutionContext` remains authoritative for call counting and
deadline enforcement across supervisor, extraction, retrieval, generation, and
ticket operations.

## Evaluation requirements

Evaluation-only traces may record all four query layers, selected candidates,
scores, relevance decisions, and fallback reasons only after ACL filtering.
Normal responses and general logs must not expose this trace.
