"""市场情绪指数定时任务.

工作日 17:10(BJT) 调用 backfill_market_sentiment_index.py --days=2 --force,
增量合成最近 2 个交易日的 composite_score (依赖 17:00 daily_eod + 17:06 ma_count
+ 17:08 style_risk + 17:09 profit_effect, 17:10 = 它们完成 1 分钟后跑).

调度配置: scheduler/market_sentiment_index_job.json
"""
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "backfill_market_sentiment_index.py"


def job_run_backfill() -> dict:
    cmd = [sys.executable, "-u", str(_SCRIPT), "--days=2", "--force"]
    logger.info("running: %s", " ".join(cmd))
    t0 = __import__("time").time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = __import__("time").time() - t0
    ok = r.returncode == 0
    level = logging.INFO if ok else logging.ERROR
    logger.log(level, "market_sentiment_index done in %.1fs | rc=%d", elapsed, r.returncode)
    if r.stdout:
        for line in r.stdout.strip().splitlines():
            logger.info("  [out] %s", line)
    if r.stderr:
        for line in r.stderr.strip().splitlines():
            logger.warning("  [err] %s", line)
    return {"ok": ok, "elapsed": round(elapsed, 1), "returncode": r.returncode}


def run() -> dict:
    return job_run_backfill()
