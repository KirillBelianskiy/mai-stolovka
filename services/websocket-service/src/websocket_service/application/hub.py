import asyncio
from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass
class ClientQueue:
    messages: asyncio.Queue[dict[str, object]]
    overflow: asyncio.Event = field(default_factory=asyncio.Event)
    shutdown: asyncio.Event = field(default_factory=asyncio.Event)


class KitchenHub:
    """Process-local fanout boundary; the Kafka consumer is owned by SCRUM-20."""

    def __init__(self, queue_size: int) -> None:
        self.queue_size = queue_size
        self.clients: dict[UUID, ClientQueue] = {}
        self.stopping = False

    def connect(self) -> tuple[UUID, ClientQueue]:
        if self.stopping:
            raise RuntimeError("Kitchen WebSocket hub is shutting down")
        client_id = uuid4()
        client = ClientQueue(messages=asyncio.Queue(maxsize=self.queue_size))
        client.messages.put_nowait({"type": "ready"})
        self.clients[client_id] = client
        return client_id, client

    def disconnect(self, client_id: UUID) -> None:
        self.clients.pop(client_id, None)

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
        for client in tuple(self.clients.values()):
            try:
                client.messages.put_nowait(message)
            except asyncio.QueueFull:
                client.overflow.set()
