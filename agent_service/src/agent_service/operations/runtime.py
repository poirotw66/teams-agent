from __future__ import annotations

from .audit import AuditStore, build_audit_store
from .classification import IssueClassifier
from .delivery.file_journal import FileJournal
from .delivery.firestore_journal import FirestoreJournal
from .delivery.primary import FileDeliveryPrimary, FirestoreDeliveryPrimary
from .delivery.worker import DeliveryWorker
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
        audit_store: AuditStore,
        store: CompositeOperationalStore | MemoryOperationalStore | FileOperationalStore,
    ) -> None:
        self.settings = settings
        self.ingestion = ingestion
        self.emitter = emitter
        self.taxonomy = taxonomy
        self.audit_store = audit_store
        self.store = store
        self.delivery_worker: DeliveryWorker | None = (
            store.delivery_worker if isinstance(store, CompositeOperationalStore) else None
        )


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
    sink_names: list[str] = []
    if resolved.bigquery_enabled:
        client = build_bigquery_client(resolved.bigquery_project)
        sinks.append(
            BigQueryEventSink(client, resolved.bigquery_dataset, resolved.bigquery_table)
        )
        sink_names.append(
            f"bigquery:{resolved.bigquery_project or 'default'}."
            f"{resolved.bigquery_dataset}.{resolved.bigquery_table}"
        )
    store: CompositeOperationalStore | MemoryOperationalStore | FileOperationalStore
    if sinks:
        if not resolved.delivery_enabled:
            raise ValueError("analytics_sink_requires_durable_delivery")
        if resolved.environment == "prod" and resolved.store_mode != "FIRESTORE":
            raise ValueError("production_delivery_requires_firestore")
        if resolved.store_mode == "FIRESTORE":
            delivery_client = build_firestore_client(
                resolved.firestore_project, resolved.firestore_database
            )
            journal = FirestoreJournal(delivery_client, resolved.delivery_firestore_collection)
            primary = FirestoreDeliveryPrimary(delivery_client, resolved.firestore_collection)
        elif resolved.store_mode == "FILE":
            journal = FileJournal(resolved.store_path / "delivery_outbox.sqlite3")
            primary = FileDeliveryPrimary(resolved.store_path)
        elif resolved.store_mode == "MEMORY" and resolved.environment in {"dev", "test"}:
            journal = FileJournal(None)
        else:
            raise ValueError("unsupported_delivery_store_mode")
        store = CompositeOperationalStore(
            primary, sinks, journal=journal, sink_names=sink_names,
            inline_sinks=resolved.delivery_inline_sinks,
            worker_options={
                "lease_seconds": resolved.delivery_lease_seconds,
                "timeout_seconds": resolved.delivery_timeout_seconds,
                "retry_base_seconds": resolved.delivery_retry_base_seconds,
                "retry_max_seconds": resolved.delivery_retry_max_seconds,
            },
        )
    else:
        store = primary
    ingestion = EventIngestionService(store, resolved)
    audit_store = build_audit_store(resolved)
    emitter = OperationalEventEmitter(ingestion, taxonomy, classifier, resolved)
    from .policy_runtime import PolicyRuntime, configure_policy_runtime

    configure_policy_runtime(PolicyRuntime.from_ops_settings(resolved))
    return OpsRuntime(
        settings=resolved,
        ingestion=ingestion,
        emitter=emitter,
        taxonomy=taxonomy,
        audit_store=audit_store,
        store=store,
    )
