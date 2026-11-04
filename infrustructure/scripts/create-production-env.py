#!/usr/bin/env python3
"""Create a mode-0600 production env file without printing its secrets."""

import argparse
import base64
import os
import secrets
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / ".env.production.example"
OUTPUT = ROOT / ".env.production"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allowed-hosts",
        required=True,
        help="Comma-separated DNS names/IPs approved for this PACS gateway; no ports.",
    )
    args = parser.parse_args()
    hosts = [host.strip() for host in args.allowed_hosts.split(",")]
    if not hosts or any(
        not host or host == "*" or any(character.isspace() for character in host)
        for host in hosts
    ):
        parser.error("--allowed-hosts must contain non-empty hostnames/IPs and cannot include '*'.")

    orthanc_password = secrets.token_urlsafe(32)
    replacements = {
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(64),
        "DJANGO_ALLOWED_HOSTS": ",".join(hosts),
        "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
        "ORTHANC_PASSWORD": orthanc_password,
        "ORTHANC_BASIC": base64.b64encode(
            f"orthanc:{orthanc_password}".encode("utf-8")
        ).decode("ascii"),
    }

    output_lines = []
    replaced = set()
    for line in TEMPLATE.read_text(encoding="utf-8").splitlines():
        key, separator, _ = line.partition("=")
        if separator and key in replacements:
            output_lines.append(f"{key}={replacements[key]}")
            replaced.add(key)
        else:
            output_lines.append(line)
    missing = replacements.keys() - replaced
    if missing:
        raise RuntimeError(
            f"Environment template is missing required keys: {', '.join(sorted(missing))}"
        )

    descriptor = os.open(OUTPUT, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as env_file:
        env_file.write("\n".join(output_lines) + "\n")
    os.chmod(OUTPUT, 0o600)
    print(f"Created {OUTPUT} with mode 0600. Secret values were not displayed.")


if __name__ == "__main__":
    main()
