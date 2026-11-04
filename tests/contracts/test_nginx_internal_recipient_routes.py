import unittest
from pathlib import Path


class InternalRecipientRouteTests(unittest.TestCase):
    def test_recipient_endpoints_are_private_but_telegram_webhook_is_routable(self) -> None:
        root = Path(__file__).resolve().parents[2]
        routes = (root / "infra/nginx/api-routes.conf").read_text()
        config = (root / "infra/nginx/nginx.conf").read_text()

        private_route = "location ^~ /api/v1/users/internal/v1/notification-recipients/ { return 404; }"
        self.assertIn(private_route, routes)
        self.assertIn("location /api/v1/users/ {", routes)
        self.assertLess(routes.index(private_route), routes.index("location /api/v1/users/ {"))
        self.assertEqual(config.count("include /etc/nginx/api-routes.conf;"), 2)
