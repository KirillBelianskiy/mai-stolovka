"""Development topic operations must never silently repair existing history."""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[2] / "infra/kafka-topic.py"
SPEC = importlib.util.spec_from_file_location("kafka_topic", PATH)
assert SPEC and SPEC.loader
topic = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = topic
SPEC.loader.exec_module(topic)

DESCRIPTION = (
    "Topic: orders.events.v1\tTopicId: abc\tPartitionCount: 1\tReplicationFactor: 1\t"
    "Configs: cleanup.policy=delete,retention.ms=604800000,min.insync.replicas=1\n"
    "Topic: orders.events.v1\tPartition: 0\tLeader: 1\tReplicas: 1\tIsr: 1\n"
)


class TopicOperationsTests(unittest.TestCase):
    def test_default_plan_never_contacts_docker(self):
        with patch.object(topic, "run") as run:
            topic.main([])
        run.assert_not_called()

    def test_existing_matching_topic_is_only_described(self):
        with patch.object(topic, "run", return_value=DESCRIPTION) as run:
            topic.main(["--check"])
        self.assertEqual(run.call_count, 1)
        self.assertIn("--describe", run.call_args.args[0])

    def test_creation_uses_explicit_settings_and_checks_result(self):
        with patch.object(topic, "run", side_effect=["", DESCRIPTION]) as run:
            topic.main(["--create-dev"])
        command = run.call_args_list[0].args[0]
        self.assertIn("--if-not-exists", command)
        self.assertIn("retention.ms=604800000", command)
        self.assertIn("cleanup.policy=delete", command)
        self.assertEqual(run.call_count, 2)

    def test_drift_is_rejected_without_alter_or_delete(self):
        for old, new in (
            ("PartitionCount: 1", "PartitionCount: 3"),
            ("ReplicationFactor: 1", "ReplicationFactor: 3"),
            ("cleanup.policy=delete", "cleanup.policy=compact"),
            ("retention.ms=604800000", "retention.ms=1000"),
            ("min.insync.replicas=1", "min.insync.replicas=2"),
            ("Isr: 1", "Isr: "),
            ("Leader: 1", "Leader: -1"),
            ("Partition: 0", "Partition: 2"),
        ):
            with self.subTest(new=new):
                with patch.object(topic, "run", return_value=DESCRIPTION.replace(old, new)) as run:
                    with self.assertRaises(topic.TopicError):
                        topic.main(["--check"])
                self.assertEqual(run.call_count, 1)

    def test_missing_or_unrecognized_metadata_is_rejected(self):
        for description in ("", "orders.events.v1", DESCRIPTION.splitlines()[0]):
            with self.subTest(description=description):
                with self.assertRaises(topic.TopicError):
                    topic.validate(description)

    def test_existing_drift_is_not_hidden_by_if_not_exists(self):
        with patch.object(topic, "run", side_effect=["", DESCRIPTION.replace("delete", "compact")]):
            with self.assertRaises(topic.TopicError):
                topic.main(["--create-dev"])

    def test_command_failure_stops_before_validation(self):
        with patch.object(topic, "run", side_effect=topic.TopicError("command failed")) as run:
            with self.assertRaises(topic.TopicError):
                topic.main(["--create-dev"])
        self.assertEqual(run.call_count, 1)

    def test_docker_calls_are_bounded_and_do_not_use_a_shell(self):
        with patch.object(topic.subprocess, "run") as run:
            run.return_value.stdout = DESCRIPTION
            topic.run(["--describe"])
        self.assertEqual(run.call_args.kwargs["timeout"], 60)
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertEqual(run.call_args.args[0][:5], ["docker", "compose", "exec", "-T", "kafka"])

    def test_raw_command_errors_are_not_exposed(self):
        failure = subprocess.CalledProcessError(1, ["docker"], stderr="private diagnostic")
        with patch.object(topic.subprocess, "run", side_effect=failure):
            with self.assertRaises(topic.TopicError) as raised:
                topic.run(["--describe"])
        self.assertNotIn("private diagnostic", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
