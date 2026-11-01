from aiokafka import AIOKafkaProducer  # type: ignore[import-untyped]
from aiokafka.admin import AIOKafkaAdminClient  # type: ignore[import-untyped]
from aiokafka.errors import (  # type: ignore[import-untyped]
    KafkaError,
    KafkaTimeoutError,
    RequestTimedOutError,
)

from order_service.application.outbox import (
    AmbiguousPublication,
    InvalidEvent,
    RetryablePublication,
)
from order_service.config import Settings


class KafkaPublisher:
    def __init__(self, settings: Settings) -> None:
        self.topic = settings.outbox_topic
        self.servers = settings.kafka_bootstrap_servers
        self.producer = AIOKafkaProducer(
            bootstrap_servers=self.servers,
            client_id="mai-order-outbox",
            enable_idempotence=True,
            acks="all",
        )

    async def start(self) -> None:
        admin = AIOKafkaAdminClient(bootstrap_servers=self.servers)
        try:
            await admin.start()
            if self.topic not in await admin.list_topics():
                raise InvalidEvent("Outbox topic must be provisioned explicitly")
        finally:
            await admin.close()
        await self.producer.start()

    async def publish(self, key: bytes, value: bytes) -> None:
        try:
            await self.producer.send_and_wait(self.topic, key=key, value=value)
        except (KafkaTimeoutError, RequestTimedOutError):
            raise AmbiguousPublication(
                "Broker result is uncertain; event remains pending"
            ) from None
        except KafkaError as error:
            if error.retriable:
                raise RetryablePublication("Temporary broker failure") from None
            raise InvalidEvent("Permanent broker error; event remains pending") from None

    async def stop(self) -> None:
        await self.producer.stop()
