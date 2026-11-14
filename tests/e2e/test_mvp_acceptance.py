import unittest
from urllib.parse import parse_qs

from mvp_acceptance import CheckFailure, launch_data, verify_idempotent_pair


class AcceptanceChecks(unittest.TestCase):
    def test_launch_fixture_cannot_use_a_real_bot_token(self):
        with self.assertRaises(ValueError):
            launch_data("123456:potential-real-token", 900001)
        fixture = parse_qs(launch_data("local-acceptance:synthetic", 900001))
        self.assertIn("900001", fixture["user"][0])
        self.assertEqual(len(fixture["hash"][0]), 64)
        self.assertNotIn("allows_write_to_pm", fixture["user"][0])

    def test_identical_replies_require_one_original_and_one_replay(self):
        order = {"id": "fixture", "status": "PENDING"}
        self.assertEqual(verify_idempotent_pair([(order, "true"), (order, "false")]), order)
        for replies in (
            [(order, "false"), (order, "false")],
            [(order, "true"), (order, None)],
            [(order, "true"), ({**order, "id": "duplicate"}, "false")],
        ):
            with self.subTest(replies=replies), self.assertRaises(CheckFailure):
                verify_idempotent_pair(replies)
