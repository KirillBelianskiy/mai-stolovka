"""Create local-only credentials without overwriting an existing environment file."""

import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / ".env"
content = (root / ".env.example").read_text()
for key in ("POSTGRES_PASSWORD", "USERS_DB_PASSWORD", "MENU_DB_PASSWORD", "ORDERS_DB_PASSWORD"):
    content = content.replace(f"{key}=\n", f"{key}={secrets.token_hex(24)}\n")

try:
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit(".env already exists; keep it or edit it explicitly") from None
with os.fdopen(descriptor, "w") as stream:
    stream.write(content)
print("Created ignored .env with independent local credentials")
