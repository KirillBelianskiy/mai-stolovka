import asyncio
from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass
class ClientQueue:
    messages: asyncio.Queue[dict[str, object]]
    overflow: asyncio.Event = field(default_factory=asyncio.Event)
    unavailable: asyncio.Event = field(default_factory=asyncio.Event)
    shutdown: asyncio.Event = field(default_factory=asyncio.Event)


class KitchenHub:
    """Process-local fanout to authenticated Kitchen sessions."""

    def __init__(self, queue_size: int, *, ready: bool = True) -> None:
        self.queue_size = queue_size
        self.clients: dict[UUID, ClientQueue] = {}
        self.stopping = False
        self.ready = ready

    def connect(self) -> tuple[UUID, ClientQueue]:
        if self.stopping or not self.ready:
            raise RuntimeError("Kitchen WebSocket hub is unavailable")
        client_id = uuid4()
        client = ClientQueue(messages=asyncio.Queue(maxsize=self.queue_size))
        client.messages.put_nowait({"type": "ready"})
        self.clients[client_id] = client
        return client_id, client

    def disconnect(self, client_id: UUID) -> None:
        self.clients.pop(client_id, None)

    def suspend(self) -> None:
        self.ready = False
        for client in self.clients.values():
            client.unavailable.set()

    async def shutdown(self) -> None:
        self.stopping = True
        for client in tuple(self.clients.values()):
            client.shutdown.set()

    async def publish_order_hint(self, order_id: UUID, version: int) -> None:
        if version < 1:
            raise ValueError("Order version must be positive")
        message: dict[str, object] = {
            "type": "order.changed",
            "order_id": str(order_id),
            "version": version,
        }
        for client in self.clients.values():
            if client.unavailable.is_set() or client.overflow.is_set():
                continue
            try:
                client.messages.put_nowait(message)
            except asyncio.QueueFull:
                client.overflow.set()
