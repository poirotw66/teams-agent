"""A minimal in-process Fake of the Firestore async client (spec §10.3).

Only the surface ``FirestoreConversationRepository`` actually uses is
modeled, and it is modeled to match ``google.cloud.firestore.AsyncClient``:

- ``client.collection(id)`` -> collection reference
- ``collection.document(id)`` -> document reference
- ``await document.get()`` -> snapshot with ``.exists`` / ``.to_dict()``
- ``await document.set(data, merge=False)``
- ``document.collection(id)`` -> subcollection reference
- ``collection.order_by(field_path, direction=...).limit(n).stream()``
  -> async iterator of snapshots

Documents are stored as deep copies so a caller mutating a dict it handed
in (or got back) cannot reach into the store -- mirroring the fact that a
real client serializes across the network.

Ordering support is deliberately limited to ``__name__`` (document id),
which is the only ordering the repository asks for.
"""

from __future__ import annotations

import copy
from typing import Any


class FakeFirestoreError(AssertionError):
    """Raised when the Fake is driven outside the modeled surface."""


class FakeDocumentSnapshot:
    def __init__(self, doc_id: str, data: dict | None) -> None:
        self.id = doc_id
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict | None:
        return copy.deepcopy(self._data) if self._data is not None else None


class FakeQuery:
    def __init__(self, collection: FakeCollectionReference) -> None:
        self._collection = collection
        self._order_by: str | None = None
        self._descending = False
        self._limit: int | None = None

    def order_by(self, field_path: str, direction: str = "ASCENDING") -> FakeQuery:
        if direction not in {"ASCENDING", "DESCENDING"}:
            raise FakeFirestoreError(f"Unknown direction: {direction!r}")
        # Real Firestore rejects a descending order on __name__ without a
        # composite index (FAILED_PRECONDITION), verified live by
        # scripts/firestore_verification.py. The Fake reproduces that so
        # the mistake cannot pass here and fail in production.
        if field_path == "__name__" and direction == "DESCENDING":
            raise FakeFirestoreError(
                "descending order on '__name__' requires a composite index in real "
                "Firestore -- order by a regular field instead"
            )
        self._order_by = field_path
        self._descending = direction == "DESCENDING"
        return self

    def limit(self, count: int) -> FakeQuery:
        self._limit = count
        return self

    def _sort_value(self, doc_id: str):
        if self._order_by is None or self._order_by == "__name__":
            return doc_id
        document = self._collection.raw_document(doc_id) or {}
        if self._order_by not in document:
            # Real Firestore omits documents missing the ordered field
            # from the result set entirely.
            return None
        return document[self._order_by]

    async def stream(self):
        doc_ids = list(self._collection.document_ids())
        if self._order_by is not None:
            keyed = [
                (self._sort_value(doc_id), doc_id)
                for doc_id in doc_ids
                if self._sort_value(doc_id) is not None
            ]
            keyed.sort(key=lambda pair: pair[0], reverse=self._descending)
            doc_ids = [doc_id for _, doc_id in keyed]
        if self._limit is not None:
            doc_ids = doc_ids[: self._limit]
        for doc_id in doc_ids:
            yield FakeDocumentSnapshot(doc_id, self._collection.raw_document(doc_id))


class FakeCollectionReference:
    def __init__(self, store: FakeFirestoreClient, path: str) -> None:
        self._store = store
        self._path = path

    def document(self, doc_id: str) -> FakeDocumentReference:
        if "/" in doc_id:
            raise FakeFirestoreError(f"Document id must not contain '/': {doc_id!r}")
        return FakeDocumentReference(self._store, f"{self._path}/{doc_id}")

    def document_ids(self) -> list[str]:
        prefix = f"{self._path}/"
        return [
            path[len(prefix) :]
            for path in self._store.paths()
            # Direct children only: a grandchild path has a further '/'.
            if path.startswith(prefix) and "/" not in path[len(prefix) :]
        ]

    def raw_document(self, doc_id: str) -> dict | None:
        return self._store.read(f"{self._path}/{doc_id}")

    def order_by(self, field_path: str, direction: str = "ASCENDING") -> FakeQuery:
        return FakeQuery(self).order_by(field_path, direction)

    def limit(self, count: int) -> FakeQuery:
        return FakeQuery(self).limit(count)

    def stream(self):
        return FakeQuery(self).stream()


class FakeDocumentReference:
    def __init__(self, store: FakeFirestoreClient, path: str) -> None:
        self._store = store
        self._path = path

    @property
    def id(self) -> str:
        return self._path.rsplit("/", 1)[-1]

    async def get(self) -> FakeDocumentSnapshot:
        self._store.reads += 1
        return FakeDocumentSnapshot(self.id, self._store.read(self._path))

    async def set(self, data: dict[str, Any], merge: bool = False) -> None:
        self._store.writes += 1
        existing = self._store.read(self._path) if merge else None
        merged = {**(existing or {}), **data}
        self._store.write(self._path, merged)

    def collection(self, collection_id: str) -> FakeCollectionReference:
        return FakeCollectionReference(self._store, f"{self._path}/{collection_id}")


class FakeFirestoreClient:
    """Root of the Fake: a flat ``path -> document`` dict.

    ``reads``/``writes`` are exposed so tests can assert on round-trip
    counts (e.g. that appending a message stays a bounded number of ops).
    """

    def __init__(self) -> None:
        self._documents: dict[str, dict] = {}
        self.reads = 0
        self.writes = 0

    def collection(self, collection_id: str) -> FakeCollectionReference:
        return FakeCollectionReference(self, collection_id)

    # -- store internals used by the reference classes ------------------

    def paths(self) -> list[str]:
        return list(self._documents.keys())

    def read(self, path: str) -> dict | None:
        data = self._documents.get(path)
        return copy.deepcopy(data) if data is not None else None

    def write(self, path: str, data: dict) -> None:
        self._documents[path] = copy.deepcopy(data)

    # -- test helpers ---------------------------------------------------

    def document_count(self, prefix: str) -> int:
        return sum(1 for path in self._documents if path.startswith(prefix))

    def all_documents(self) -> dict[str, dict]:
        return copy.deepcopy(self._documents)
