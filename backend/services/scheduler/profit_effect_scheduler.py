"""赚钱效应定时任务.

工作日 17:09(BJT) 调用 backfill_profit_effect.py --days=2 --force,
增量回填最近 2 个交易日的赚钱效应合成得分.

调度配置: scheduler/profit_effect_job.json
"""
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "backfill_profit_effect.py"


def job_run_backfill() -> dict:
    cmd = [sys.executable, "-u", str(_SCRIPT), "--days=2", "--force"]
    logger.info("running: %s", " ".join(cmd))
    t0 = __import__("time").time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = __import__("time").time() - t0
    ok = r.returncode == 0
    level = logging.INFO if ok else logging.ERROR
    logger.log(level, "profit_effect done in %.1fs | rc=%d", elapsed, r.returncode)
    if r.stdout:
        for line in r.stdout.strip().splitlines():
            logger.info("  [out] %s", line)
    if r.stderr:
        for line in r.stderr.strip().splitlines():
            logger.warning("  [err] %s", line)
    return {"ok": ok, "elapsed": round(elapsed, 1), "returncode": r.returncode}


def run() -> dict:
    return job_run_backfill()
