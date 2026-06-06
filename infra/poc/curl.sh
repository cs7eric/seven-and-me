#!/usr/bin/env bash
# POC: Eastmoney 板块 / 概念 / 行业 探测
# 跑这个脚本能看到哪些 endpoint 通了、字段长什么样。
# Windows PowerShell / Git Bash / WSL 都能直接 bash curl.sh 跑。

# =============================================================================
# 通用 headers（emweb / push2 都用这套，跟项目里 STOCK_EASTMONEY_HEADERS 一致）
# =============================================================================
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# emweb 用 https://quote.eastmoney.com/ 作 referer
EMWEB_H=(-H "User-Agent: $UA" -H "Accept: application/json, text/plain, */*" -H "Referer: https://quote.eastmoney.com/" -H "Origin: https://quote.eastmoney.com")

# =============================================================================
# 能力 1: 某只票 → 所属板块 / 概念 / 行业
# =============================================================================

# 1.1) 个股 F10 → 29 条 "所属板块 ssbk" + 8 条 "核心题材 hxtc"（★ 主路径，强烈推荐）
#     600519 = 贵州茅台，BK0438 = 食品饮料
curl -sS "${EMWEB_H[@]}" \
  "https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax?code=SH600519" \
  | python -c "import sys, json; d=json.load(sys.stdin); print('ssbk count:', len(d.get('ssbk') or [])); print('hxtc count:', len(d.get('hxtc') or [])); [print('  ssbk:', x.get('BOARD_CODE'), x.get('BOARD_NAME')) for x in (d.get('ssbk') or [])[:5]]"

echo

# 1.2) 个股 F10 公司概况（jbzl + fxxg，基础信息，不含板块）
curl -sS "${EMWEB_H[@]}" \
  "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax?code=SH600519" \
  | python -c "import sys, json; d=json.load(sys.stdin); print('sections:', list(d.keys()))"

echo

# 1.3) 试 002594 比亚迪（看不同票的数据结构）
curl -sS "${EMWEB_H[@]}" \
  "https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax?code=SZ002594" \
  | python -c "import sys, json; d=json.load(sys.stdin); print('ssbk count:', len(d.get('ssbk') or [])); [print('  ssbk:', x.get('BOARD_CODE'), x.get('BOARD_NAME')) for x in (d.get('ssbk') or [])[:5]]"

echo

# 1.4) 试 688981 中芯国际（科创板）
curl -sS "${EMWEB_H[@]}" \
  "https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax?code=SH688981" \
  | python -c "import sys, json; d=json.load(sys.stdin); print('ssbk count:', len(d.get('ssbk') or [])); [print('  ssbk:', x.get('BOARD_CODE'), x.get('BOARD_NAME')) for x in (d.get('ssbk') or [])[:5]]"

echo

# =============================================================================
# 能力 2: 板块 BK code → 板块成分股
# =============================================================================
# 注意：push2.eastmoney.com 我这边连不上，你那边可能可以。如果不行就放弃。
# 这条接口是 Eastmoney 行情核心，fs=b:{BK code} 是关键。

# 2.1) BK0438 (食品饮料) → 成分股
curl -sS "${EMWEB_H[@]}" \
  "http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=20&po=1&np=1&fltt=2&invt=2&fid=f3&fs=b%3ABK0438&fields=f1,f2,f3,f4,f5,f6,f12,f14" \
  | python -c "import sys, json; d=json.load(sys.stdin); rows=(d.get('data') or {}).get('diff') or []; print('BK0438 total:', (d.get('data') or {}).get('total')); [print('  ', r.get('f12'), r.get('f14')) for r in rows[:5]]"

echo

# 2.2) BK0475 (白酒) → 成分股
curl -sS "${EMWEB_H[@]}" \
  "http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=20&po=1&np=1&fltt=2&invt=2&fid=f3&fs=b%3ABK0475&fields=f1,f2,f3,f4,f5,f6,f12,f14" \
  | python -c "import sys, json; d=json.load(sys.stdin); rows=(d.get('data') or {}).get('diff') or []; print('BK0475 total:', (d.get('data') or {}).get('total')); [print('  ', r.get('f12'), r.get('f14')) for r in rows[:5]]"

echo

# 2.3) BK1033 (人工智能概念) → 成分股
curl -sS "${EMWEB_H[@]}" \
  "http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=20&po=1&np=1&fltt=2&invt=2&fid=f3&fs=b%3ABK1033&fields=f1,f2,f3,f4,f5,f6,f12,f14" \
  | python -c "import sys, json; d=json.load(sys.stdin); rows=(d.get('data') or {}).get('diff') or []; print('BK1033 total:', (d.get('data') or {}).get('total')); [print('  ', r.get('f12'), r.get('f14')) for r in rows[:5]]"

echo

# =============================================================================
# 能力 3: Eastmoney 全量 板块 / 行业 / 概念 列表
# =============================================================================

# 3.1) 申万一级行业 m:90+t:1
curl -sS "${EMWEB_H[@]}" \
  "http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=200&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m%3A90%2Bt%3A1&fields=f1,f2,f3,f4,f12,f14" \
  | python -c "import sys, json; d=json.load(sys.stdin); rows=(d.get('data') or {}).get('diff') or []; print('申万一级 total:', (d.get('data') or {}).get('total')); [print('  ', r.get('f12'), r.get('f14')) for r in rows[:5]]"

echo

# 3.2) 申万二级行业 m:90+t:2
curl -sS "${EMWEB_H[@]}" \
  "http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=200&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m%3A90%2Bt%3A2&fields=f1,f2,f3,f4,f12,f14" \
  | python -c "import sys, json; d=json.load(sys.stdin); rows=(d.get('data') or {}).get('diff') or []; print('申万二级 total:', (d.get('data') or {}).get('total')); [print('  ', r.get('f12'), r.get('f14')) for r in rows[:5]]"

echo

# 3.3) 概念板块 m:90+t:4
curl -sS "${EMWEB_H[@]}" \
  "http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=200&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m%3A90%2Bt%3A4&fields=f1,f2,f3,f4,f12,f14" \
  | python -c "import sys, json; d=json.load(sys.stdin); rows=(d.get('data') or {}).get('diff') or []; print('概念 total:', (d.get('data') or {}).get('total')); [print('  ', r.get('f12'), r.get('f14')) for r in rows[:5]]"

echo

# =============================================================================
# 备选方案（如果 push2 真的全部连不上）:
# 1) 公司行情走 AKShare：
#    pip install akshare
#    python -c "import akshare as ak; df = ak.stock_board_concept_name_em(); print(df.head())"
#    ak.stock_board_concept_name_em()      # 概念列表
#    ak.stock_board_industry_name_em()    # 行业列表
#    ak.stock_board_concept_cons_em("BK1033")  # 概念成分股
#    ak.stock_board_industry_cons_em("BK0438")  # 行业成分股
# 2) 走 akshare 的 stock_individual_info_em(symbol="600519")
# =============================================================================
