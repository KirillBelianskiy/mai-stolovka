"""Run the real bundled Kafka CLI only against UUID-named disposable topics."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def topic_tool(monkeypatch):
    if not os.getenv("MAI_TEST_KAFKA_BOOTSTRAP_SERVERS"):
        pytest.skip("Run the isolated integration runner with its Compose Kafka broker")
    path = Path(__file__).resolve().parents[3] / "infra/kafka-topic.py"
    spec = importlib.util.spec_from_file_location("integration_topic_tool", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    name = "mai-test-topic-operations-" + uuid4().hex
    monkeypatch.setattr(module, "TOPIC", name)
    try:
        yield module
    finally:
        module.run(["--delete", "--if-exists", "--topic", name])


def test_real_cli_creates_checks_and_reuses_matching_topic(topic_tool) -> None:
    topic_tool.main(["--create-dev"])
    topic_tool.main(["--check"])
    topic_tool.main(["--create-dev"])


def test_real_cli_refuses_existing_retention_drift_without_repair(topic_tool) -> None:
    topic_tool.run(
        [
            "--create",
            "--topic",
            topic_tool.TOPIC,
            "--partitions",
            "1",
            "--replication-factor",
            "1",
            "--config",
            "cleanup.policy=delete",
            "--config",
            "retention.ms=3600000",
            "--config",
            "min.insync.replicas=1",
        ]
    )
    with pytest.raises(topic_tool.TopicError, match="retention.ms"):
        topic_tool.main(["--create-dev"])
    description = topic_tool.run(["--describe", "--topic", topic_tool.TOPIC])
    assert "retention.ms=3600000" in description
