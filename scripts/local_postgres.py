"""Throwaway local Postgres for running the tests against the production engine.

No Docker needed: uses the `pgserver` wheel (bundled Postgres binaries), which
only ships for Python <= 3.12, hence the separate interpreter:

    uv run --no-project --python 3.12 --with pgserver scripts/local_postgres.py

It prints a TEST_DATABASE_URL and keeps running until Ctrl+C; then in another shell:

    TEST_DATABASE_URL=<printed url> uv run pytest

The data directory is temporary and removed on exit. Stop it with Ctrl+C:
killing the terminal (or `uv`) on Windows leaves postgres.exe running.
Tests wipe the database between tests, so never point TEST_DATABASE_URL at a
database you care about.
"""

import signal
import sys
import tempfile
import time

import pgserver


def main() -> None:
    data_dir = tempfile.mkdtemp(prefix="santa-pg-")
    server = pgserver.get_server(data_dir, cleanup_mode="delete")
    server.psql("CREATE DATABASE santa_test;")
    host_part = server.get_uri().split("@", 1)[1].split("/", 1)[0]
    user_part = server.get_uri().split("//", 1)[1].split("@", 1)[0]
    print(f"TEST_DATABASE_URL=postgresql://{user_part}@{host_part}/santa_test", flush=True)

    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
