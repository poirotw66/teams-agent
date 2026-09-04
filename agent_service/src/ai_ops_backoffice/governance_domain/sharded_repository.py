"""Sharded Firestore governance persistence for growth beyond the 1 MiB doc limit.

Layout:
  {collection}/pointers/current     — small revision + active pointers
  {collection}/prompts/{id}
  {collection}/prompt_versions/{id}
  {collection}/eval_runs/{id}
  {collection}/audits/{id}
  {collection}/snapshots/{revision} — optional full-state checkpoint (LAB migrate)

``load()`` reassembles a ``GovernanceState`` for the existing service layer.
``mutate()`` updates the pointer transactionally and writes only changed entities.
"""

from __future__ import annotations

from typing import Any

from .errors import GovernanceConflictError
from .models import GovernanceState
from .repository import Mutation

_ENTITY_SPECS: tuple[tuple[str, str], ...] = (
    ("prompts", "prompt_id"),
    ("prompt_versions", "version_id"),
    ("eval_runs", "run_id"),
    ("model_configs", "config_id"),
    ("model_versions", "version_id"),
    ("flags", "flag_id"),
    ("flag_versions", "version_id"),
    ("role_changes", "change_id"),
    ("retention_policies", "version_id"),
    ("masking_policies", "version_id"),
    ("audits", "audit_id"),
    ("idempotency", "key"),
)


class ShardedFirestoreGovernanceRepository:
    """Split governance entities across Firestore documents with a pointer head."""

    def __init__(
        self,
        client: Any,
        *,
        collection: str = "ai_ops_governance_state",
        transaction_runner: Any | None = None,
    ) -> None:
        self._client = client
        self._root = client.collection(collection)
        self._pointer = self._root.document("pointers").collection("meta").document("current")
        self._transaction_runner = transaction_runner

    def _entity_doc(self, kind: str, entity_id: str) -> Any:
        return self._root.document(kind).collection("items").document(entity_id)

    def _read_collection(self, kind: str) -> list[dict[str, Any]]:
        return [snapshot.to_dict() for snapshot in self._root.document(kind).collection("items").stream()]

    def load(self) -> GovernanceState:
        pointer = self._pointer.get()
        if not pointer.exists:
            # Backward-compatible: fall back to monolithic ``current`` if present.
            legacy = self._root.document("current").get()
            if legacy.exists:
                return GovernanceState.model_validate(legacy.to_dict())
            return GovernanceState()
        payload = {
            "revision": int(pointer.to_dict().get("revision") or 1),
            "prompts": self._read_collection("prompts"),
            "prompt_versions": self._read_collection("prompt_versions"),
            "eval_runs": self._read_collection("eval_runs"),
            "model_configs": self._read_collection("model_configs"),
            "model_versions": self._read_collection("model_versions"),
            "flags": self._read_collection("flags"),
            "flag_versions": self._read_collection("flag_versions"),
            "role_changes": self._read_collection("role_changes"),
            "retention_policies": self._read_collection("retention_policies"),
            "masking_policies": self._read_collection("masking_policies"),
            "audits": self._read_collection("audits"),
            "idempotency": self._read_collection("idempotency"),
            "revoked_principals": list(pointer.to_dict().get("revoked_principals") or ()),
        }
        return GovernanceState.model_validate(payload)

    def mutate(self, operation: Mutation) -> dict[str, Any]:
        def transaction_operation(transaction: Any) -> dict[str, Any]:
            pointer_snap = self._pointer.get(transaction=transaction)
            if pointer_snap.exists:
                current = self.load()
                current = current.model_copy(
                    update={"revision": int(pointer_snap.to_dict().get("revision") or 1)}
                )
            else:
                legacy = self._root.document("current").get(transaction=transaction)
                current = (
                    GovernanceState.model_validate(legacy.to_dict())
                    if legacy.exists
                    else GovernanceState()
                )
            next_state, result = operation(current)
            if next_state.revision != current.revision + 1:
                raise GovernanceConflictError("governance state revision must increment")
            self._write_state(transaction, previous=current, next_state=next_state)
            return result

        if self._transaction_runner is not None:
            return self._transaction_runner(transaction_operation, self._client.transaction())
        try:
            from google.cloud.firestore_v1.transaction import transactional
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("FIRESTORE governance repository requires google-cloud-firestore") from error
        return transactional(transaction_operation)(self._client.transaction())

    def _write_state(
        self,
        transaction: Any,
        *,
        previous: GovernanceState,
        next_state: GovernanceState,
    ) -> None:
        transaction.set(
            self._pointer,
            {
                "revision": next_state.revision,
                "revoked_principals": list(next_state.revoked_principals),
                "activePromptIds": [
                    item.prompt_id for item in next_state.prompts if item.active_version_id
                ],
                "schema": "sharded-v1",
            },
        )
        previous_dump = previous.model_dump(mode="python")
        next_dump = next_state.model_dump(mode="python")
        for kind, id_field in _ENTITY_SPECS:
            prev_items = {
                str(item.get(id_field) or ""): item
                for item in (previous_dump.get(kind) or [])
                if item.get(id_field)
            }
            next_items = {
                str(item.get(id_field) or ""): item
                for item in (next_dump.get(kind) or [])
                if item.get(id_field)
            }
            for entity_id, item in next_items.items():
                if prev_items.get(entity_id) == item:
                    continue
                transaction.set(self._entity_doc(kind, entity_id), item)
            for entity_id in prev_items:
                if entity_id not in next_items:
                    transaction.delete(self._entity_doc(kind, entity_id))
