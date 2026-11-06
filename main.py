"""Run the whole pipeline with one command (ASSIGNMENT.md §5, D56).

    python main.py                              parse -> load -> dedupe -> notify (dry run: drafts only)
    python main.py --preview                    ... then list the live targets (sends nothing)
    python main.py --send-live [--max-sends N]  ... then send notices via the Gmail MCP server

Each step is its own script (src/*.py) and can also be run on its own. A step
that fails stops the pipeline, so later steps never run on stale input.
"""

import argparse
import os
import subprocess
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def run_step(name, script, extra_args=()):
    """Run one step's script with the same Python; stop the pipeline if it fails."""
    print(f"\n=== {name}: python {script} {' '.join(extra_args)}".rstrip())
    start = time.time()
    result = subprocess.run([sys.executable, os.path.join(PROJECT_ROOT, script), *extra_args],
                            cwd=PROJECT_ROOT)
    seconds = time.time() - start
    if result.returncode != 0:
        print(f"=== {name} FAILED (exit code {result.returncode}) after {seconds:.1f} s; stopping.")
        sys.exit(result.returncode)
    print(f"=== {name} done in {seconds:.1f} s")
    return seconds


def main():
    parser = argparse.ArgumentParser(description="Enron dedup pipeline: parse -> load -> dedupe -> notify.")
    parser.add_argument("--send-live", action="store_true", help="send notices live (passed to notify.py)")
    parser.add_argument("--preview", action="store_true", help="list live targets only (passed to notify.py)")
    parser.add_argument("--max-sends", type=int, help="live sends this run (passed to notify.py)")
    args = parser.parse_args()

    notify_args = []
    if args.send_live:
        notify_args.append("--send-live")
    if args.preview:
        notify_args.append("--preview")
    if args.max_sends is not None:
        notify_args += ["--max-sends", str(args.max_sends)]

    timings = {
        "1. parse": run_step("1. parse", "src/parse_emails.py"),
        "2. load": run_step("2. load", "src/load_db.py"),
        "3. dedupe": run_step("3. dedupe", "src/detect_duplicates.py"),
        "4. notify": run_step("4. notify", "src/notify.py", notify_args),
    }
    print("\n=== Pipeline finished: " + "   ".join(f"{k} {v:.1f} s" for k, v in timings.items())
          + f"   total {sum(timings.values()):.1f} s")


if __name__ == "__main__":
    main()
