"""Read-only local route preflight; never an end-to-end acceptance verdict."""

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

SERVICES = ("user", "menu", "order", "notification", "websocket")
MAX_BODY = 1024 * 1024


def local_origin(value: str) -> str:
    """Keep preflight away from production and from launch URLs containing credentials."""
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.port is None
        or not 0 < parsed.port < 65536
    ):
        raise ValueError("Use an explicit local HTTP origin and port, without launch data")
    return value.rstrip("/")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read(base: str, path: str) -> tuple[int, object]:
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request(base + path, headers={"Accept": "application/json,text/html"}, method="GET")
    try:
        response = opener.open(request, timeout=5)
    except HTTPError as error:
        response = error
    with response:
        payload = response.read(MAX_BODY + 1)
        if len(payload) > MAX_BODY:
            raise ValueError("Response exceeds preflight size limit")
        content_type = response.headers.get_content_type()
        body = (
            json.loads(payload) if content_type == "application/json" else payload.decode("utf-8")
        )
        return response.status, body


def run(customer: str, staff: str, reader=read) -> dict:
    origins = {"customer": local_origin(customer), "staff": local_origin(staff)}
    if origins["customer"] == origins["staff"]:
        raise ValueError("Customer and staff origins must be distinct")
    checks = []
    routes = (
        ["/"]
        + [f"/health/{service}/ready" for service in SERVICES]
        + [
            "/api/v1/menu/categories",
            "/api/v1/menu/items?limit=1&offset=0",
            "/api/v1/users/me",
            "/api/v1/orders/",
            "/api/v1/orders/wallet",
        ]
    )
    for surface, base in origins.items():
        for path in routes:
            result = {"surface": surface, "path": path, "passed": False}
            try:
                status, body = reader(base, path)
                result["http_status"] = status
                if path == "/":
                    passed = status == 200 and isinstance(body, str) and "<html" in body.lower()
                elif path.startswith("/health/"):
                    service = path.split("/")[2]
                    passed = status == 200 and body == {
                        "service": f"{service}-service",
                        "status": "ready",
                    }
                elif path.endswith("categories"):
                    passed = status == 200 and isinstance(body, list)
                elif path.startswith("/api/v1/menu/items"):
                    passed = (
                        status == 200
                        and isinstance(body, dict)
                        and isinstance(body.get("items"), list)
                    )
                else:
                    passed = status == 401
                result["passed"] = passed
            except (OSError, ValueError, TimeoutError):
                # Upstream bodies/diagnostics may contain credentials or private data.
                result["error"] = "Request or response validation failed"
            checks.append(result)
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "scope": "anonymous local HTTP route preflight",
        "origins": origins,
        "preflight_passed": all(check["passed"] for check in checks),
        "journey_acceptance": "not_run",
        "unexecuted_scenarios": [f"A{i}" for i in range(1, 9)],
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--customer-origin", required=True)
    parser.add_argument("--staff-origin", required=True)
    parser.add_argument("--source-revision", required=True, help="40-character local source SHA")
    parser.add_argument(
        "--output", type=Path, required=True, help="New report file; never overwritten"
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_revision):
        parser.error("source-revision must be an exact 40-character Git SHA")
    try:
        # Check the output before network access; preserve any existing evidence.
        with args.output.open("x", encoding="utf-8") as stream:
            report = run(args.customer_origin, args.staff_origin)
            report["source_revision"] = args.source_revision
            report["deployed_revision_verified"] = False
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except (OSError, ValueError) as error:
        parser.exit(2, f"Preflight could not complete ({type(error).__name__}).\n")
    print("Route preflight passed." if report["preflight_passed"] else "Route preflight failed.")
    print("Full journey acceptance: NOT RUN. See the report and docs/verification-mvp.md.")
    return 0 if report["preflight_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
