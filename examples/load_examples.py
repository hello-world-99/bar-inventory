"""Load all example data into a fresh install, in order:
  1. the example week (load_week.py, moved to the seven days before yesterday),
  2. the owner's own POS day for yesterday (python -m app.cli seed-example),
  3. operations that run some products low (load_low_stock.py, over the last nine hours).

Run by examples.bat / ./examples.sh inside a one-off backend container (no Python needed on the computer):
    docker compose run --rm --no-deps -e BAR_ADMIN_PASSWORD -v ./examples:/examples:ro backend python /examples/load_examples.py http://web
Meant for a fresh install: on a database that already has the example reports it stops at the first refusal.
"""

import subprocess
import sys

import load_low_stock
import load_week


def main() -> None:
    tok = load_week.login()
    if load_week.ok(load_week.call("GET", "/sales-imports", token=tok), "sales reports")["items"]:
        sys.exit("This database already has POS reports (examples loaded before, or real data): nothing done.\n"
                 "The examples are meant for a fresh install. To start over with an empty database, see README, 'Start over'.")
    print("1/3  example week")
    load_week.main()
    print("\n2/3  the owner's example day (yesterday)")
    r = subprocess.run([sys.executable, "-m", "app.cli", "seed-example"], cwd="/app", capture_output=True, text=True)
    print((r.stdout + r.stderr).strip())
    if r.returncode != 0:
        sys.exit("seed-example failed")
    print("\n3/3  operations that run some products low")
    load_low_stock.main()


if __name__ == "__main__":
    main()
