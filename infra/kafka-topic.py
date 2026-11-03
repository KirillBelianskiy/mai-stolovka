"""Plan, create or check the fixed local-development Order topic in Compose."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOPIC = "orders.events.v1"
SETTINGS = {
    "cleanup.policy": "delete",
    "retention.ms": "604800000",
    "min.insync.replicas": "1",
}


class TopicError(Exception):
    """Topic state is unavailable or incompatible with the development contract."""


def run(arguments: list[str]) -> str:
    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "kafka",
                "/opt/kafka/bin/kafka-topics.sh",
                "--bootstrap-server",
                "kafka:29092",
                *arguments,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise TopicError(
            f"Kafka topic command failed ({type(error).__name__}); "
            "check Docker, broker readiness and local operator logs."
        ) from None
    return result.stdout


def validate(description: str) -> None:
    lines = [line.strip() for line in description.splitlines() if line.strip()]
    summaries = [line for line in lines if "PartitionCount:" in line]
    partitions = [line for line in lines if re.search(r"\bPartition:", line)]
    if len(summaries) != 1 or len(partitions) != 1:
        raise TopicError(
            "Expected exactly one topic summary and one partition; no repair attempted."
        )
    summary = summaries[0]
    expected = {
        "Topic": re.escape(TOPIC),
        "PartitionCount": "1",
        "ReplicationFactor": "1",
    }
    for field, value in expected.items():
        if not re.search(rf"(?:^|\s){field}:\s*{value}(?=\s|$)", summary):
            raise TopicError(f"Unexpected topic {field}; no repair attempted.")
    config_text = summary.partition("Configs:")[2].strip()
    configs = dict(re.findall(r"([\w.]+)=([^,\s]+)", config_text))
    for key, value in SETTINGS.items():
        if configs.get(key) != value:
            raise TopicError(f"Missing or incompatible explicit {key}; no repair attempted.")
    partition = partitions[0]
    for field, value in {"Topic": re.escape(TOPIC), "Partition": "0"}.items():
        if not re.search(rf"(?:^|\s){field}:\s*{value}(?=\s|$)", partition):
            raise TopicError(f"Unexpected partition {field}; no repair attempted.")
    leader = re.search(r"\bLeader:\s*(\d+)(?=\s|$)", partition)
    replicas = re.search(r"\bReplicas:\s*(\d+)(?=\s|$)", partition)
    isr = re.search(r"\bIsr:\s*(\d+)(?=\s|$)", partition)
    if not leader or not replicas or not isr or len({m[1] for m in (leader, replicas, isr)}) != 1:
        raise TopicError("Development partition needs its single replica online and in sync.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--check", action="store_true", help="Inspect without changing the topic")
    actions.add_argument(
        "--create-dev",
        action="store_true",
        help="Create if absent, then check; never alter or delete",
    )
    args = parser.parse_args(argv)
    if not args.check and not args.create_dev:
        print(
            json.dumps(
                {
                    "mode": "plan-only",
                    "topic": TOPIC,
                    "partitions": 1,
                    "replication_factor": 1,
                    "configs": SETTINGS,
                    "scope": "local Compose development only",
                },
                indent=2,
            )
        )
        return
    if args.create_dev:
        command = [
            "--create",
            "--if-not-exists",
            "--topic",
            TOPIC,
            "--partitions",
            "1",
            "--replication-factor",
            "1",
        ]
        for key, value in SETTINGS.items():
            command.extend(["--config", f"{key}={value}"])
        run(command)
    validate(run(["--describe", "--topic", TOPIC]))
    print(f"{TOPIC}: local development configuration and single-replica availability verified")


if __name__ == "__main__":
    try:
        main()
    except TopicError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
