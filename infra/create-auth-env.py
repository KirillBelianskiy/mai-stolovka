"""Generate local JWT keys without printing them or overwriting an existing key pair."""

import base64
import os
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / ".env"
if not path.is_file():
    raise SystemExit("Create .env with infra/create-local-env.py first")
content = path.read_text()
configured = dict(
    line.split("=", 1) for line in content.splitlines() if "=" in line and not line.startswith("#")
)
if configured.get("JWT_PRIVATE_KEY_BASE64") or configured.get("JWT_PUBLIC_KEY_BASE64"):
    raise SystemExit("JWT keys already exist; explicit key rotation is required to replace them")
private = subprocess.run(
    ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072"],
    check=True,
    capture_output=True,
    timeout=60,
).stdout
public = subprocess.run(
    ["openssl", "pkey", "-pubout"],
    input=private,
    check=True,
    capture_output=True,
    timeout=10,
).stdout
lines = [
    line
    for line in content.splitlines()
    if not line.startswith(("JWT_PRIVATE_KEY_BASE64=", "JWT_PUBLIC_KEY_BASE64="))
]
lines += [
    "JWT_PRIVATE_KEY_BASE64=" + base64.b64encode(private).decode(),
    "JWT_PUBLIC_KEY_BASE64=" + base64.b64encode(public).decode(),
]
if "TELEGRAM_BOT_TOKEN" not in configured:
    lines.append("TELEGRAM_BOT_TOKEN=")
os.chmod(path, 0o600)
path.write_text("\n".join(lines) + "\n")
print("Generated local JWT keys in ignored .env; Telegram token remains user-supplied")
