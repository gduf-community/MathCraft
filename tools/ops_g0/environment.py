"""Create only isolated, ignored Phoenix configuration; never print secrets."""

import argparse
import json
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / ".scratch/ops-g0-20261112"


def prepare() -> dict[str, object]:
    """Preserve any existing isolated credentials and create missing local files."""
    HOME.mkdir(parents=True, exist_ok=True)
    private = HOME / "private.json"
    if not private.exists():
        with private.open("x", encoding="utf-8") as handle:
            json.dump(
                {
                    "phoenix_secret": "g0a9" + secrets.token_hex(32),
                    "admin_secret": "g0b8" + secrets.token_hex(32),
                },
                handle,
                indent=2,
            )
    credentials = json.loads(private.read_text(encoding="utf-8"))
    if credentials["admin_secret"] == credentials["phoenix_secret"]:
        raise ValueError("The two isolated secrets must be independent")
    (HOME / "phoenix-data").mkdir(exist_ok=True)
    environment = HOME / "phoenix.env"
    if not environment.exists():
        values = {
            "OPS_G0_HOME": HOME.as_posix(),
            "PHOENIX_ENABLE_AUTH": "true",
            "PHOENIX_SECRET": credentials["phoenix_secret"],
            "PHOENIX_ADMIN_SECRET": credentials["admin_secret"],
            "PHOENIX_WORKING_DIR": "/mnt/data",
            "PHOENIX_SQL_DATABASE_URL": "sqlite:////mnt/data/phoenix.db",
            "PHOENIX_HOST": "0.0.0.0",
            "PHOENIX_PORT": "6006",
        }
        with environment.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    return {
        "home": str(HOME),
        "private_configuration_exists": private.is_file(),
        "independent_secrets": credentials["admin_secret"] != credentials["phoenix_secret"],
        "loopback_url": "http://127.0.0.1:6016",
        "server_authentication_enabled": True,
        "business_configuration_read": False,
    }


def main() -> None:
    """Prepare without changing any business configuration or existing credential."""
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(prepare(), indent=2))


if __name__ == "__main__":
    main()
