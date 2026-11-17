"""Make the admin dashboard's password hash (and, once, its session secret).

    python -m admin.password             # asks twice on a terminal
    printf '%s' "$PW" | python -m admin.password --stdin
    python -m admin.password --secret    # also a fresh ADMIN_SECRET

Prints `ADMIN_PASSWORD_HASH=...` (and `ADMIN_SECRET=...`) lines for .env.prod.
`./makhzan admin password` runs this in the ingestion container, writes the
lines into .env.prod and recreates the `admin` service. The password itself
is never printed or stored.
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import sys

from admin.auth import hash_password

#: Shorter than this is refused: the page faces only the tailnet, but it can
#: pause the crawl and rule on products.
MIN_LENGTH = 12


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m admin.password", description=__doc__)
    parser.add_argument("--stdin", action="store_true", help="read the password from stdin")
    parser.add_argument("--secret", action="store_true", help="also print a new ADMIN_SECRET")
    args = parser.parse_args(argv)
    if args.stdin:
        password = sys.stdin.read().rstrip("\r\n")
    else:
        password = getpass.getpass("Admin password: ")
        if getpass.getpass("Again: ") != password:
            print("The two did not match.", file=sys.stderr)
            return 1
    if len(password) < MIN_LENGTH:
        print(f"Use at least {MIN_LENGTH} characters.", file=sys.stderr)
        return 1
    print(f"ADMIN_PASSWORD_HASH={hash_password(password)}")
    if args.secret:
        print(f"ADMIN_SECRET={secrets.token_hex(32)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
