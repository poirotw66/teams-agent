from __future__ import annotations

from .audit import MemoryAuditStore
from .classification import IssueClassifier
from .emitter import OperationalEventEmitter
from .ingestion import EventIngestionService
from .settings import OpsSettings
from .stores.bigquery_sink import BigQueryEventSink, build_bigquery_client
from .stores.composite_store import CompositeOperationalStore
from .stores.file_store import FileOperationalStore
from .stores.firestore_store import FirestoreOperationalStore, build_firestore_client
from .stores.memory_store import MemoryOperationalStore
from .taxonomy import TaxonomyRepository


class OpsRuntime:
    def __init__(
        self,
        settings: OpsSettings,
        ingestion: EventIngestionService,
        emitter: OperationalEventEmitter,
        taxonomy: TaxonomyRepository,
        audit_store: MemoryAuditStore,
        store: CompositeOperationalStore | MemoryOperationalStore | FileOperationalStore,
    ) -> None:
        self.settings = settings
        self.ingestion = ingestion
        self.emitter = emitter
        self.taxonomy = taxonomy
        self.audit_store = audit_store
        self.store = store


def _build_primary_store(settings: OpsSettings) -> MemoryOperationalStore | FileOperationalStore | FirestoreOperationalStore:
    if settings.store_mode == "MEMORY":
        return MemoryOperationalStore()
    if settings.store_mode == "FIRESTORE":
        client = build_firestore_client(settings.firestore_project, settings.firestore_database)
        return FirestoreOperationalStore(client, settings.firestore_collection)
    return FileOperationalStore(settings.store_path)


def build_ops_runtime(settings: OpsSettings | None = None) -> OpsRuntime | None:
    resolved = settings or OpsSettings.from_env()
    if not resolved.enabled:
        return None
    taxonomy = TaxonomyRepository(resolved.taxonomy_path)
    classifier = IssueClassifier(taxonomy, resolved.classification_rules_path)
    primary = _build_primary_store(resolved)
    sinks: list[object] = []
    if resolved.bigquery_enabled:
        client = build_bigquery_client(resolved.bigquery_project)
        sinks.append(
            BigQueryEventSink(client, resolved.bigquery_dataset, resolved.bigquery_table)
        )
    store: CompositeOperationalStore | MemoryOperationalStore | FileOperationalStore
    if sinks:
        store = CompositeOperationalStore(primary, sinks)
    else:
        store = primary
    ingestion = EventIngestionService(store, resolved)
    audit_store = MemoryAuditStore()
    emitter = OperationalEventEmitter(ingestion, taxonomy, classifier, resolved)
    return OpsRuntime(
        settings=resolved,
        ingestion=ingestion,
        emitter=emitter,
        taxonomy=taxonomy,
        audit_store=audit_store,
        store=store,
    )
