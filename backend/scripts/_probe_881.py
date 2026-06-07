"""探针: 试 881289 / 881087 在 eltdx 各接口能不能拉数据."""
import sys
sys.path.insert(0, ".")
import eltdx

CODES = ["881289", "881087"]

with eltdx.TdxClient(pool_size=4, timeout=8.0) as client:
    client.connect()

    # 1) 批量快照 (0x054c)
    print("=== 1) get_snapshots (0x054c) ===")
    try:
        snaps = client.quotes.get_snapshots(CODES)
        for s in snaps:
            print(f"  {s.full_code} name={s.name} last={s.last_price} change_pct={s.change_pct} amount={s.amount}")
    except Exception as e:
        print(f"  ERR: {e}")

    # 2) 代码表查 881289 / 881087 是不是指数类
    print()
    print("=== 2) codes.list 找 881289 / 881087 ===")
    try:
        sh_codes = client.codes.all("sh", page_size=2000)
        for c in sh_codes:
            if c.code in CODES:
                print(f"  {c.full_code} name={c.name} pre_close={c.pre_close_price}")
        bj_codes = client.codes.all("bj", page_size=2000)
        for c in bj_codes:
            if c.code in CODES:
                print(f"  {c.full_code} name={c.name} pre_close={c.pre_close_price}")
    except Exception as e:
        print(f"  ERR: {e}")

    # 3) K-line (日线)
    print()
    print("=== 3) bars.get day count=2 ===")
    for code in CODES:
        try:
            kline = client.bars.get(code, period="day", count=2)
            bars = kline.bars or []
            print(f"  {code} ({kline.exchange}): {[(b.time.strftime('%Y-%m-%d'), b.close) for b in bars]}")
        except Exception as e:
            print(f"  {code} ERR: {e}")

    # 4) 看下 K-line kind="index" 试不试
    print()
    print("=== 4) bars.get day kind=index count=2 ===")
    for code in CODES:
        try:
            kline = client.bars.get(code, period="day", count=2, kind="index")
            bars = kline.bars or []
            print(f"  {code} (kind=index): {[(b.time.strftime('%Y-%m-%d'), b.close) for b in bars]}")
        except Exception as e:
            print(f"  {code} ERR: {e}")
