import argparse
import getpass
import hashlib
import os
from pathlib import Path
import subprocess


_ACL = """\
user default off
user gateway on #{gateway_hash} ~rl:bucket:* ~rl:policy-index:* ~rl:policy:* ~rl:service-config:* +auth +hello +ping +select +client|setname +client|setinfo +time +type +hmget +hset +pexpire +get +eval +evalsha +script|load
user policy-service on #{policy_hash} ~rl:policy:* ~rl:policy-index:* ~rl:service-config:* +auth +hello +ping +select +client|setname +client|setinfo +type +get +hget +set +hset +eval +evalsha +script|load
user monitoring on #{monitor_hash} ~* +auth +hello +ping +select +client|setname +client|setinfo +info +config|get +cluster|info +cluster|nodes
"""


def _password_hash(name: str) -> str:
    while True:
        password = getpass.getpass(f"{name} Redis password (32+ characters): ")
        if len(password) < 32:
            print("Password must contain at least 32 characters.")
            continue
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            print("Passwords did not match.")
            continue
        return hashlib.sha256(password.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a Redis ACL file without printing credentials."
    )
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    hashes = {
        "gateway_hash": _password_hash("Gateway"),
        "policy_hash": _password_hash("Policy Service"),
        "monitor_hash": _password_hash("Monitoring"),
    }
    output = args.output.resolve()
    if output.exists():
        raise SystemExit("Refusing to overwrite an existing ACL file.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_ACL.format(**hashes), encoding="utf-8")
    if os.name == "nt":
        try:
            principal = subprocess.run(
                ["whoami"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            subprocess.run(
                [
                    "icacls",
                    str(output),
                    "/inheritance:r",
                    "/grant:r",
                    f"{principal}:(F)",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            output.unlink(missing_ok=True)
            raise SystemExit(
                "Could not restrict ACL file permissions; generated file "
                "was removed."
            ) from error
    else:
        try:
            os.chmod(output, 0o600)
        except OSError as error:
            output.unlink(missing_ok=True)
            raise SystemExit(
                "Could not restrict ACL file permissions; generated file "
                "was removed."
            ) from error
    print(f"Redis ACL file created at {output}. Store passwords separately.")


if __name__ == "__main__":
    main()
