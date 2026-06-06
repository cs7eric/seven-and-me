# Eastmoney 板块/概念/行业 POC 探测 — PowerShell 单条命令版
# 跑法:
#   powershell -ExecutionPolicy Bypass -File "F:\dev-repo\mp4-to-word-new\infra\poc\curl-commands.ps1"
# 或双击运行 / VSCode 右键 "Run with PowerShell"

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ProgressPreference = 'SilentlyContinue'

$UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
$emwebHeaders = @(
    "User-Agent: $UA",
    "Accept: application/json, text/plain, */*",
    "Referer: https://quote.eastmoney.com/",
    "Origin: https://quote.eastmoney.com"
)

# 把 curl 输出写到临时文件 → Python 读文件 → 避免 PowerShell pipeline 转码破坏 JSON
$tmp = Join-Path $env:TEMP "em_poc_$PID.json"

function Show-Json($file, $script) {
    python -c $script $file
}

function Section($name) {
    Write-Host ""
    Write-Host "=== $name ===" -ForegroundColor Cyan
}

# =============================================================================
# 能力 1: 个股 → 所属板块 / 概念 / 行业
# =============================================================================

Section "1.1 茅台 (600519) 所属板块 [emweb CoreConception]"
curl.exe -sS @emwebHeaders `
  "https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax?code=SH600519" `
  -o $tmp
Show-Json $tmp @'
import sys, json
d = json.load(open(sys.argv[1], encoding="utf-8"))
b = d.get("ssbk") or []
h = d.get("hxtc") or []
print(f"ssbk 数量: {len(b)}")
print(f"hxtc 数量: {len(h)}")
print("--- ssbk 字段 (第一条) ---")
print(json.dumps(b[0], ensure_ascii=False, indent=2)) if b else None
print("--- 板块前 8 条 ---")
for x in b[:8]:
    print(f"  {x.get('BOARD_CODE'):>6}  {x.get('BOARD_NAME'):<12}  rank={x.get('BOARD_RANK')}  precise={x.get('IS_PRECISE')}")
'@

Section "1.2 茅台 CompanySurvey (公司概况)"
curl.exe -sS @emwebHeaders `
  "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax?code=SH600519" `
  -o $tmp
Show-Json $tmp @'
import sys, json
d = json.load(open(sys.argv[1], encoding="utf-8"))
print("sections:", list(d.keys()))
for k in list(d.keys())[:5]:
    v = d[k]
    if isinstance(v, list):
        print(f"  {k}: list[{len(v)}]")
    else:
        print(f"  {k}: {str(v)[:80]}")
'@

Section "1.3 比亚迪 (002594) 所属板块"
curl.exe -sS @emwebHeaders `
  "https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax?code=SZ002594" `
  -o $tmp
Show-Json $tmp @'
import sys, json
d = json.load(open(sys.argv[1], encoding="utf-8"))
b = d.get("ssbk") or []
print(f"ssbk 数量: {len(b)}")
for x in b[:8]:
    print(f"  {x.get('BOARD_CODE'):>6}  {x.get('BOARD_NAME'):<12}  rank={x.get('BOARD_RANK')}")
'@

Section "1.4 中芯国际 (688981) — 科创板"
curl.exe -sS @emwebHeaders `
  "https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax?code=SH688981" `
  -o $tmp
Show-Json $tmp @'
import sys, json
d = json.load(open(sys.argv[1], encoding="utf-8"))
b = d.get("ssbk") or []
print(f"ssbk 数量: {len(b)}")
for x in b[:8]:
    print(f"  {x.get('BOARD_CODE'):>6}  {x.get('BOARD_NAME'):<12}  rank={x.get('BOARD_RANK')}")
'@

# =============================================================================
# 能力 2: 板块 BK code → 成分股 (push2 — 你那边网络拦了，预计 Empty reply)
# =============================================================================

Section "2.1 BK0438 食品饮料 成分股 (push2)"
$r = curl.exe -sS -m 5 -o $tmp -w '%{http_code}' @emwebHeaders `
  'http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=20&po=1&np=1&fltt=2&invt=2&fid=f3&fs=b%3ABK0438&fields=f1,f2,f3,f4,f5,f6,f12,f14'
Write-Host "  HTTP: $r"
if ($LASTEXITCODE -ne 0 -or (Test-Path $tmp) -eq $false -or (Get-Item $tmp).Length -lt 5) {
    Write-Host "  ✗ push2 失败 — 你这边网络也拦截了 push2.eastmoney.com" -ForegroundColor Yellow
    Write-Host "  → 备用方案: 见末尾 'AKShare 备选' 段" -ForegroundColor Yellow
} else {
    Show-Json $tmp @'
import sys, json
d = json.load(open(sys.argv[1], encoding="utf-8"))
rows = (d.get("data") or {}).get("diff") or []
print(f"total: {(d.get('data') or {}).get('total')}")
for r in rows[:8]:
    print(f"  {r.get('f12')}  {r.get('f14')}")
'@
}

Section "2.2 BK0475 白酒 成分股 (push2)"
curl.exe -sS -m 5 -o $tmp @emwebHeaders `
  'http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=20&po=1&np=1&fltt=2&invt=2&fid=f3&fs=b%3ABK0475&fields=f1,f2,f3,f4,f5,f6,f12,f14'
if ((Test-Path $tmp) -and (Get-Item $tmp).Length -gt 5) {
    Show-Json $tmp @'
import sys, json
d = json.load(open(sys.argv[1], encoding="utf-8"))
rows = (d.get("data") or {}).get("diff") or []
print(f"total: {(d.get('data') or {}).get('total')}")
for r in rows[:8]:
    print(f"  {r.get('f12')}  {r.get('f14')}")
'@
} else {
    Write-Host "  ✗ push2 不可达" -ForegroundColor Yellow
}

Section "2.3 BK1033 人工智能 成分股 (push2)"
curl.exe -sS -m 5 -o $tmp @emwebHeaders `
  'http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=20&po=1&np=1&fltt=2&invt=2&fid=f3&fs=b%3ABK1033&fields=f1,f2,f3,f4,f5,f6,f12,f14'
if ((Test-Path $tmp) -and (Get-Item $tmp).Length -gt 5) {
    Show-Json $tmp @'
import sys, json
d = json.load(open(sys.argv[1], encoding="utf-8"))
rows = (d.get("data") or {}).get("diff") or []
print(f"total: {(d.get('data') or {}).get('total')}")
for r in rows[:8]:
    print(f"  {r.get('f12')}  {r.get('f14')}")
'@
} else {
    Write-Host "  ✗ push2 不可达" -ForegroundColor Yellow
}

# =============================================================================
# 能力 3: 全量 行业 / 概念 列表 (push2)
# =============================================================================

Section "3.1 申万一级行业 (push2)"
curl.exe -sS -m 5 -o $tmp @emwebHeaders `
  'http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=200&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m%3A90%2Bt%3A1&fields=f1,f2,f3,f4,f12,f14'
if ((Test-Path $tmp) -and (Get-Item $tmp).Length -gt 5) {
    Show-Json $tmp @'
import sys, json
d = json.load(open(sys.argv[1], encoding="utf-8"))
rows = (d.get("data") or {}).get("diff") or []
print(f"total: {(d.get('data') or {}).get('total')}")
for r in rows[:5]:
    print(f"  {r.get('f12')}  {r.get('f14')}")
'@
} else {
    Write-Host "  ✗ push2 不可达" -ForegroundColor Yellow
}

Section "3.2 申万二级行业 (push2)"
curl.exe -sS -m 5 -o $tmp @emwebHeaders `
  'http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=200&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m%3A90%2Bt%3A2&fields=f1,f2,f3,f4,f12,f14'
if ((Test-Path $tmp) -and (Get-Item $tmp).Length -gt 5) {
    Show-Json $tmp @'
import sys, json
d = json.load(open(sys.argv[1], encoding="utf-8"))
rows = (d.get("data") or {}).get("diff") or []
print(f"total: {(d.get('data') or {}).get('total')}")
for r in rows[:5]:
    print(f"  {r.get('f12')}  {r.get('f14')}")
'@
} else {
    Write-Host "  ✗ push2 不可达" -ForegroundColor Yellow
}

Section "3.3 概念板块 (push2)"
curl.exe -sS -m 5 -o $tmp @emwebHeaders `
  'http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=200&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m%3A90%2Bt%3A4&fields=f1,f2,f3,f4,f12,f14'
if ((Test-Path $tmp) -and (Get-Item $tmp).Length -gt 5) {
    Show-Json $tmp @'
import sys, json
d = json.load(open(sys.argv[1], encoding="utf-8"))
rows = (d.get("data") or {}).get("diff") or []
print(f"total: {(d.get('data') or {}).get('total')}")
for r in rows[:5]:
    print(f"  {r.get('f12')}  {r.get('f14')}")
'@
} else {
    Write-Host "  ✗ push2 不可达" -ForegroundColor Yellow
}

# =============================================================================
# AKShare 备选方案 (push2 全挂时兜底)
# =============================================================================

Section "AKShare 备选 (push2 不可达时用这个)"
$akshareCheck = python -c "import akshare" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  akshare 未安装 → 装一下:" -ForegroundColor Yellow
    Write-Host "    pip install akshare" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  装完后跑这些命令验证:" -ForegroundColor Green
    Write-Host '    python -c "import akshare as ak; df=ak.stock_board_industry_name_em(); print(df.head(8))"'
    Write-Host '    python -c "import akshare as ak; df=ak.stock_board_concept_name_em(); print(df.head(8))"'
    Write-Host '    python -c "import akshare as ak; df=ak.stock_board_industry_cons_em(''BK0438''); print(df.head(8))"'
    Write-Host '    python -c "import akshare as ak; df=ak.stock_board_concept_cons_em(''BK1033''); print(df.head(8))"'
} else {
    Write-Host "  ✓ akshare 已装" -ForegroundColor Green
    Write-Host ""
    Write-Host "  全量行业:"
    python -c "import akshare as ak; df=ak.stock_board_industry_name_em(); print(df.head(8).to_string())"
    Write-Host ""
    Write-Host "  概念板块前 8 条:"
    python -c "import akshare as ak; df=ak.stock_board_concept_name_em(); print(df.head(8).to_string())"
    Write-Host ""
    Write-Host "  BK0438 食品饮料 成分股前 8 条:"
    python -c "import akshare as ak; df=ak.stock_board_industry_cons_em('BK0438'); print(df.head(8).to_string())"
    Write-Host ""
    Write-Host "  BK1033 人工智能概念 成分股前 8 条:"
    python -c "import akshare as ak; df=ak.stock_board_concept_cons_em('BK1033'); print(df.head(8).to_string())"
}

Remove-Item $tmp -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=== 跑完 ===" -ForegroundColor Green
Write-Host "  把终端输出直接复制贴给我就行" -ForegroundColor Green
Write-Host "  如果中文乱码,把脚本顶上的 [Console]::OutputEncoding 改 utf8 + 用 chcp 65001" -ForegroundColor Green
