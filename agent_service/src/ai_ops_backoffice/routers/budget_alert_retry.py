"""Alert delivery retry helper for budget alert routes."""

from __future__ import annotations

from ..faq_domain import FaqNotFoundError


async def retry_alert_delivery_action(
    *,
    budget_service,
    notification_dispatcher,
    alert_id: str,
    delivery_id: str,
    actor,
) -> dict[str, object]:
    alert = budget_service.alert_detail(alert_id, actor=actor)
    if delivery_id not in {item["delivery_id"] for item in alert["deliveries"]}:
        raise FaqNotFoundError(delivery_id)
    result = budget_service.retry_delivery(delivery_id, actor=actor)
    delivery_item = result.get("delivery")
    if delivery_item:
        await notification_dispatcher.dispatch_delivery(delivery_item, actor=actor)
    updated_alert = budget_service.alert_detail(alert_id, actor=actor)
    updated_delivery = next(
        item for item in updated_alert["deliveries"] if item["delivery_id"] == delivery_id
    )
    return {"delivery": updated_delivery}
