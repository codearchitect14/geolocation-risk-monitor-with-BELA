"""Run the harvest jobs on fixed intervals and keep heartbeat files for monitoring.

Each job runs as a subprocess with a timeout. Results are recorded in
data/raw/_status/<job>.json by the job scripts themselves; this loop also records
crashes and timeouts. Stop with Ctrl+C or SIGTERM. For unattended use run it under
launchd, systemd, cron (`--once`), or a container supervisor.

  python data/scripts/scheduler.py            run forever
  python data/scripts/scheduler.py --once     run every due job once and exit
  python data/scripts/scheduler.py --report   print job health and exit
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import FrameType

import common

SCRIPTS = Path(__file__).resolve().parent
log = common.get_logger("scheduler")


@dataclasses.dataclass(frozen=True)
class Job:
    name: str
    script: str
    args: tuple[str, ...]
    interval_seconds: int
    timeout_seconds: int
    requires_env: tuple[str, ...] = ()


JOBS = [
    Job("usgs", "pull_usgs.py", ("--feed", "all_day"), 300, 120),
    Job("nws", "pull_nws.py", (), 300, 120, ("MS_CONTACT",)),
    Job("firms", "pull_firms.py", ("--lookback-days", "2"), 3 * 3600, 1800, ("FIRMS_MAP_KEY",)),
    Job("gdelt", "harvest_gdelt.py", ("--timespan", "3h"), 1800, 1500),
    Job("reliefweb", "pull_reliefweb.py", (), 6 * 3600, 600, ("RELIEFWEB_APPNAME",)),
]


def configured(job: Job) -> bool:
    import os

    if job.name == "nws" and os.environ.get("NWS_USER_AGENT"):
        return True
    return all(os.environ.get(name, "").strip() for name in job.requires_env)


def run_job(job: Job) -> bool:
    command = [sys.executable, str(SCRIPTS / job.script), *job.args]
    started = time.monotonic()
    try:
        result = subprocess.run(command, timeout=job.timeout_seconds, check=False)  # noqa: S603
    except subprocess.TimeoutExpired:
        log.error("%s timed out after %ds", job.name, job.timeout_seconds)
        common.write_status(job.name, False, {"error": "timeout"})
        return False
    ok = result.returncode == 0
    log.info("%s finished rc=%d in %.0fs", job.name, result.returncode, time.monotonic() - started)
    if not ok and not (common.status_dir() / f"{job.name}.json").exists():
        common.write_status(job.name, False, {"error": f"exit code {result.returncode}"})
    return ok


def report() -> int:
    """Print job health. Returns 1 if any configured job has failed recently."""
    now = common.utcnow()
    unhealthy = 0
    print(f"{'job':10} {'runs':>5} {'fail':>5} {'consec':>6}  {'first_run':20} {'last_success':20}  state")
    for job in JOBS:
        state = common.read_json(common.status_dir() / f"{job.name}.json", None)
        if state is None:
            print(
                f"{job.name:10} {'-':>5} {'-':>5} {'-':>6}  {'-':20} {'-':20}  "
                f"{'never run' if configured(job) else 'not configured'}"
            )
            continue
        last_ok = state.get("last_success")
        stale = True
        if last_ok:
            age = now - dt.datetime.fromisoformat(last_ok.replace("Z", "+00:00"))
            stale = age > dt.timedelta(seconds=job.interval_seconds * 3)
        verdict = "ok" if not stale and state.get("consecutive_failures", 0) == 0 else "ATTENTION"
        unhealthy += verdict != "ok"
        print(
            f"{job.name:10} {state['runs']:>5} {state.get('failures', 0):>5} "
            f"{state.get('consecutive_failures', 0):>6}  {state.get('first_run', '-'):20} "
            f"{last_ok or '-':20}  {verdict}"
        )
    return 1 if unhealthy else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--job", action="append", choices=[j.name for j in JOBS])
    args = parser.parse_args(argv)
    if args.report:
        return report()

    jobs = [j for j in JOBS if not args.job or j.name in args.job]
    skipped = [j.name for j in jobs if not configured(j)]
    jobs = [j for j in jobs if configured(j)]
    if skipped:
        log.warning("skipping unconfigured jobs: %s", ", ".join(skipped))

    stop = False

    def handle(_signum: int, _frame: FrameType | None) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGTERM, handle)

    next_run = {j.name: 0.0 for j in jobs}
    while not stop:
        now = time.monotonic()
        for job in jobs:
            if stop:
                break
            if now >= next_run[job.name]:
                run_job(job)
                next_run[job.name] = time.monotonic() + job.interval_seconds
        if args.once:
            break
        time.sleep(5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
