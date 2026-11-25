from typing import Protocol
from uuid import UUID

from notification_service.domain.delivery import (
    BlockReport,
    DeliveryResult,
    Recipient,
    ReportResult,
)
from notification_service.infrastructure.dispatch import DispatchStore


class RecipientService(Protocol):
    async def resolve(self, user_id: UUID) -> Recipient: ...
    async def report(self, report: BlockReport) -> ReportResult: ...


class Telegram(Protocol):
    async def send(self, chat_id: int, order_number: str) -> DeliveryResult: ...


async def dispatch_once(store: DispatchStore, user: RecipientService, bot: Telegram) -> bool:
    report = await store.due_report()
    if report is not None:
        if report.state == "refresh":
            current = await user.resolve(report.user_id)
            result: ReportResult = "retry" if current.state == "dependency_unavailable" else "stale"
        else:
            result = await user.report(report)
        await store.complete_report(report, result)

    claim = await store.claim()
    if claim is None:
        return report is not None
    recipient = await user.resolve(claim.user_id)
    if await store.authorize(claim, recipient):
        assert recipient.chat_id is not None
        result_send = await bot.send(recipient.chat_id, claim.order_number)
        await store.complete(claim, recipient, result_send)
    return True
