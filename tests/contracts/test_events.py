import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

EVENTS = Path(__file__).resolve().parents[2] / "packages/contracts/events"
SCHEMA = json.loads((EVENTS / "envelope-v1.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


class EventContractTests(unittest.TestCase):
    def test_schema_and_all_examples(self) -> None:
        Draft202012Validator.check_schema(SCHEMA)
        paths = list((EVENTS / "examples").glob("*.json"))
        self.assertEqual(len(paths), 3)
        for path in paths:
            with self.subTest(path=path.name):
                VALIDATOR.validate(json.loads(path.read_text()))

    def test_missing_envelope_fields_are_rejected(self) -> None:
        example = json.loads((EVENTS / "examples/order_created.json").read_text())
        for field in SCHEMA["required"]:
            candidate = copy.deepcopy(example)
            del candidate[field]
            with self.subTest(field=field):
                self.assertFalse(VALIDATOR.is_valid(candidate))

    def test_invalid_identifiers_version_timestamp_and_payload_are_rejected(self) -> None:
        example = json.loads((EVENTS / "examples/order_created.json").read_text())
        invalid = {
            "event_id": "invalid",
            "aggregate_id": "invalid",
            "event_version": 2,
            "event_type": "UNKNOWN",
            "occurred_at": "not-a-timestamp",
            "payload": [],
        }
        for field, value in invalid.items():
            candidate = copy.deepcopy(example)
            candidate[field] = value
            with self.subTest(field=field):
                self.assertFalse(VALIDATOR.is_valid(candidate))


class OrderPayloadTests(unittest.TestCase):
    def test_created_payload_cannot_claim_ready_or_omit_owner(self) -> None:
        example = json.loads((EVENTS / "examples/order_created.json").read_text())
        candidate = copy.deepcopy(example)
        candidate["payload"]["status"] = "READY"
        self.assertFalse(VALIDATOR.is_valid(candidate))
        del example["payload"]["user_id"]
        self.assertFalse(VALIDATOR.is_valid(example))

    def test_transition_payload_must_match_state_machine(self) -> None:
        example = json.loads((EVENTS / "examples/order_status_updated.json").read_text())
        example["payload"]["previous_status"] = "PENDING"
        example["payload"]["status"] = "COMPLETED"
        self.assertFalse(VALIDATOR.is_valid(example))

    def test_cancellation_payload_requires_previous_state(self) -> None:
        example = json.loads((EVENTS / "examples/order_cancelled.json").read_text())
        del example["payload"]["previous_status"]
        self.assertFalse(VALIDATOR.is_valid(example))


if __name__ == "__main__":
    unittest.main()
