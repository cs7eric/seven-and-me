"""风格风险偏好定时任务.

工作日 17:08(BJT) 调用 backfill_style_risk_appetite.py --days=2 --force,
增量回填最近 2 个交易日的中证1000-沪深300 5日收益 spread.

调度配置: scheduler/style_risk_appetite_job.json
"""
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "backfill_style_risk_appetite.py"


def job_run_backfill() -> dict:
    """增量回填: 最近 2 天, force 覆盖."""
    cmd = [sys.executable, "-u", str(_SCRIPT), "--days=2", "--force"]
    logger.info("running: %s", " ".join(cmd))
    t0 = __import__("time").time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = __import__("time").time() - t0
    ok = r.returncode == 0
    level = logging.INFO if ok else logging.ERROR
    logger.log(level, "style_risk_appetite done in %.1fs | rc=%d", elapsed, r.returncode)
    if r.stdout:
        for line in r.stdout.strip().splitlines():
            logger.info("  [out] %s", line)
    if r.stderr:
        for line in r.stderr.strip().splitlines():
            logger.warning("  [err] %s", line)
    return {"ok": ok, "elapsed": round(elapsed, 1), "returncode": r.returncode}


def run() -> dict:
    return job_run_backfill()
