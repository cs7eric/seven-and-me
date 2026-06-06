# 一键跑全流程: init + 各组 + run-failed + aggregate
# 第一轮: shard-size/组, 间歇 SleepFirst
# 重试: run-failed 之前/之后 sleep SleepRetry
#
# 用法:
#   .\backend\scripts\refresh_stock_universe_loop.ps1                                              # 默认 600/组
#   .\backend\scripts\refresh_stock_universe_loop.ps1 -ShardSize 1000                              # 1000/组
#   .\backend\scripts\refresh_stock_universe_loop.ps1 -ShardSize 1000 -SleepFirst 60 -SleepRetry 150

param(
    [int]$ShardSize = 800,
    [int]$SleepFirst = 100,
    [int]$SleepRetry = 5
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $ProjectRoot

Write-Host "=== refresh_stock_universe_loop.ps1 ===" -ForegroundColor Cyan
Write-Host "  project:     $ProjectRoot"
Write-Host "  shard_size:  $ShardSize (init --shard-size)"
Write-Host "  sleep_first: ${SleepFirst}s (第一轮每组)"
Write-Host "  sleep_retry: ${SleepRetry}s (run-failed 之前/之后)"
Write-Host ""

# 1. init
Write-Host "============================================="
Write-Host "[1/init] init (拉 code+name, 拆 $ShardSize/组)" -ForegroundColor Yellow
Write-Host "============================================="
python -m backend.scripts.refresh_stock_universe_init --shard-size $ShardSize
Write-Host ""

# 1.5 clean (清空上次 loop 留下的 _failed_codes.json + snapshot)
Write-Host "============================================="
Write-Host "[1.5/clean] 清空昨天 failed + snapshot" -ForegroundColor Yellow
Write-Host "============================================="
python -m backend.scripts.refresh_stock_universe_sharded clean
Write-Host ""



# 2-N. 跑第一轮每组
$groupsDir = Join-Path $ProjectRoot "reference\stock-universe\groups"
$groupFiles = Get-ChildItem $groupsDir -Filter "*.json" -ErrorAction SilentlyContinue | Sort-Object Name
$total = $groupFiles.Count
Write-Host "  -> 共 $total 个组" -ForegroundColor Cyan

for ($i = 0; $i -lt $groupFiles.Count; $i++) {
    $groupId = $groupFiles[$i].BaseName
    Write-Host ""
    Write-Host "============================================="
    Write-Host "[$($i + 2)/$($total + 3)] run group $groupId" -ForegroundColor Yellow
    Write-Host "============================================="
    python -m backend.scripts.refresh_stock_universe_sharded run --group $groupId
    Write-Host "[sleep ${SleepFirst}s]"
    Start-Sleep -Seconds $SleepFirst
}

# run-failed 之前 间歇
Write-Host ""
Write-Host "============================================="
Write-Host "[$($total + 2)/$($total + 3)] sleep ${SleepRetry}s before run-failed" -ForegroundColor Yellow
Write-Host "============================================="
Start-Sleep -Seconds $SleepRetry

Write-Host ""
Write-Host "============================================="
Write-Host "[$($total + 3)/$($total + 3)] run-failed + aggregate" -ForegroundColor Yellow
Write-Host "============================================="
python -m backend.scripts.refresh_stock_universe_sharded run-failed
Write-Host "[sleep ${SleepRetry}s]"
Start-Sleep -Seconds $SleepRetry
python -m backend.scripts.refresh_stock_universe_sharded aggregate
Write-Host ""
Write-Host "=== final status ===" -ForegroundColor Cyan
python -m backend.scripts.refresh_stock_universe_sharded status
