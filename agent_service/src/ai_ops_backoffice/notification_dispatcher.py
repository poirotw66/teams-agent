from __future__ import annotations

import logging
import smtplib
from collections.abc import Callable
from email.message import EmailMessage
from typing import Any

import httpx

from agent_service.operations.access import ActorContext
from agent_service.operations.contracts import utc_now

from .budget_domain import BudgetService, NotificationDelivery
from .settings import BackofficeSettings

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """Dispatches operational alerts to external notification channels (Teams, Email, Notification Center)."""

    def __init__(
        self,
        settings: BackofficeSettings,
        budget_service: BudgetService,
        *,
        http_transport: httpx.AsyncBaseTransport | None = None,
        email_sender: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self._settings = settings
        self._budget_service = budget_service
        self._http_transport = http_transport
        self._email_sender = email_sender

    async def dispatch_delivery(
        self,
        delivery: dict[str, Any] | NotificationDelivery,
        *,
        actor: ActorContext,
    ) -> dict[str, Any]:
        if isinstance(delivery, dict):
            delivery_id = str(delivery["delivery_id"])
            channel = str(delivery["channel"])
            target_id = str(delivery["target_id"])
            summary = str(delivery["summary"])
            status = str(delivery["status"])
            alert_id = str(delivery["alert_id"])
        else:
            delivery_id = delivery.delivery_id
            channel = delivery.channel
            target_id = delivery.target_id
            summary = delivery.summary
            status = delivery.status
            alert_id = delivery.alert_id

        if status == "SENT":
            return {"delivery_id": delivery_id, "status": "SENT", "skipped": True}

        if channel == "NOTIFICATION_CENTER":
            return self._budget_service.record_delivery_attempt(
                delivery_id,
                success=True,
                error=None,
                actor=actor,
            )

        if channel == "TEAMS":
            return await self._dispatch_teams(
                delivery_id=delivery_id,
                alert_id=alert_id,
                target_id=target_id,
                summary=summary,
                actor=actor,
            )

        if channel == "EMAIL":
            return await self._dispatch_email(
                delivery_id=delivery_id,
                alert_id=alert_id,
                target_id=target_id,
                summary=summary,
                actor=actor,
            )

        return self._budget_service.record_delivery_attempt(
            delivery_id,
            success=False,
            error=f"Unsupported notification channel: {channel}",
            actor=actor,
        )

    def _get_alert_context(self, alert_id: str) -> dict[str, str]:
        base_url = (
            self._settings.knowledge_portal_url.rstrip("/")
            if self._settings.knowledge_portal_url
            else f"http://{self._settings.host}:{self._settings.port}"
        )
        try:
            state = self._budget_service._repository.load()
            alert = next((a for a in state.alerts if a.alert_id == alert_id), None)
        except Exception:
            alert = None

        if alert is None:
            return {
                "reason": "System Alert Triggered",
                "context_page": "Operations Overview",
                "deep_link": f"{base_url}/overview",
            }

        reason = alert.message or f"{alert.alert_type} ({alert.severity}) on {alert.scope_type}:{alert.scope_id}"
        if alert.alert_type == "SYNC_FAILURE":
            context_page = "Knowledge Portal / 同步管理"
            deep_link = f"{base_url}/knowledge?tab=sync&jobId={alert.scope_id}"
        elif alert.alert_type == "API_ANOMALY":
            context_page = "Operations Summary / 系統概況"
            deep_link = f"{base_url}/overview"
        else:
            context_page = "Cost & Budget / 預算管理"
            deep_link = f"{base_url}/budgets?alertId={alert.alert_id}"

        return {
            "reason": reason,
            "context_page": context_page,
            "deep_link": deep_link,
        }

    async def _dispatch_teams(
        self,
        *,
        delivery_id: str,
        alert_id: str,
        target_id: str,
        summary: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        webhook_url = self._settings.teams_webhook_url
        if not webhook_url and target_id.startswith("http"):
            webhook_url = target_id

        if not webhook_url:
            return self._budget_service.record_delivery_attempt(
                delivery_id,
                success=False,
                error="Teams webhook URL is not configured (AI_OPS_TEAMS_WEBHOOK_URL)",
                actor=actor,
            )

        alert_info = self._get_alert_context(alert_id)
        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": "🔔 AI Operations Alert Notification",
                                "weight": "Bolder",
                                "size": "Medium",
                            },
                            {
                                "type": "TextBlock",
                                "text": summary,
                                "wrap": True,
                            },
                            {
                                "type": "FactSet",
                                "facts": [
                                    {"title": "Alert ID", "value": alert_id},
                                    {"title": "Delivery ID", "value": delivery_id},
                                    {"title": "Reason", "value": alert_info["reason"]},
                                    {"title": "Context", "value": alert_info["context_page"]},
                                    {"title": "Deep Link", "value": alert_info["deep_link"]},
                                    {"title": "Target", "value": target_id},
                                    {"title": "Timestamp", "value": utc_now().isoformat()},
                                ],
                            },
                        ],
                        "actions": [
                            {
                                "type": "Action.OpenUrl",
                                "title": "前往處理頁面 (Open in Backoffice)",
                                "url": alert_info["deep_link"],
                            }
                        ],
                    },
                }
            ],
            "text": f"{summary} (Reason: {alert_info['reason']} | Link: {alert_info['deep_link']})",
        }

        try:
            async with httpx.AsyncClient(
                transport=self._http_transport,
                timeout=15.0,
            ) as client:
                response = await client.post(webhook_url, json=payload)
                if response.is_success:
                    return self._budget_service.record_delivery_attempt(
                        delivery_id,
                        success=True,
                        error=None,
                        actor=actor,
                    )
                return self._budget_service.record_delivery_attempt(
                    delivery_id,
                    success=False,
                    error=f"Teams webhook returned HTTP {response.status_code}: {response.text[:200]}",
                    actor=actor,
                )
        except Exception as exc:
            logger.warning("Failed to dispatch Teams notification %s: %s", delivery_id, exc)
            return self._budget_service.record_delivery_attempt(
                delivery_id,
                success=False,
                error=f"Teams delivery failed: {type(exc).__name__}: {str(exc)}",
                actor=actor,
            )

    async def _dispatch_email(
        self,
        *,
        delivery_id: str,
        alert_id: str,
        target_id: str,
        summary: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        alert_info = self._get_alert_context(alert_id)
        if self._email_sender is not None:
            try:
                full_body = (
                    f"{summary}\n\n"
                    f"Reason: {alert_info['reason']}\n"
                    f"Context: {alert_info['context_page']}\n"
                    f"Backoffice Link: {alert_info['deep_link']}\n"
                )
                self._email_sender(target_id, f"[AI Operations Alert] {summary}", full_body)
                return self._budget_service.record_delivery_attempt(
                    delivery_id,
                    success=True,
                    error=None,
                    actor=actor,
                )
            except Exception as exc:
                return self._budget_service.record_delivery_attempt(
                    delivery_id,
                    success=False,
                    error=f"Email sender error: {type(exc).__name__}: {str(exc)}",
                    actor=actor,
                )

        if not self._settings.smtp_host:
            return self._budget_service.record_delivery_attempt(
                delivery_id,
                success=False,
                error="SMTP host is not configured (AI_OPS_SMTP_HOST)",
                actor=actor,
            )

        try:
            msg = EmailMessage()
            msg["Subject"] = f"[AI Ops Alert] {summary[:80]}"
            msg["From"] = self._settings.smtp_from
            msg["To"] = target_id if "@" in target_id else self._settings.smtp_from
            msg.set_content(
                f"AI Operations Alert Notification\n\n"
                f"Alert ID: {alert_id}\n"
                f"Delivery ID: {delivery_id}\n"
                f"Target: {target_id}\n"
                f"Time: {utc_now().isoformat()}\n"
                f"Reason: {alert_info['reason']}\n"
                f"Context Page: {alert_info['context_page']}\n"
                f"Backoffice Link: {alert_info['deep_link']}\n\n"
                f"Summary:\n{summary}\n"
            )

            with smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port, timeout=15) as server:
                if self._settings.smtp_user and self._settings.smtp_password:
                    server.starttls()
                    server.login(self._settings.smtp_user, self._settings.smtp_password)
                server.send_message(msg)

            return self._budget_service.record_delivery_attempt(
                delivery_id,
                success=True,
                error=None,
                actor=actor,
            )
        except Exception as exc:
            logger.warning("Failed to dispatch Email notification %s: %s", delivery_id, exc)
            return self._budget_service.record_delivery_attempt(
                delivery_id,
                success=False,
                error=f"SMTP delivery failed: {type(exc).__name__}: {str(exc)}",
                actor=actor,
            )

    async def dispatch_pending(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        state = self._budget_service._repository.load()
        pending = [d for d in state.deliveries if d.status == "PENDING"]
        results: list[dict[str, Any]] = []
        for delivery in pending:
            res = await self.dispatch_delivery(delivery, actor=actor)
            results.append(res)
        return results

    async def dispatch_for_alert(self, alert_id: str, *, actor: ActorContext) -> list[dict[str, Any]]:
        state = self._budget_service._repository.load()
        deliveries = [
            d for d in state.deliveries
            if d.alert_id == alert_id and d.status == "PENDING"
        ]
        results: list[dict[str, Any]] = []
        for delivery in deliveries:
            res = await self.dispatch_delivery(delivery, actor=actor)
            results.append(res)
        return results
