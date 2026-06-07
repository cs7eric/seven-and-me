# 一键跑全流程: init + 各组 + run-failed 循环 + aggregate
# 第一轮: shard-size/组, 间歇 SleepFirst
# 重试: run-failed 循环到 failed = 0 (无上限 max_rounds 轮)
#
# 用法:
#   .\backend\scripts\refresh_stock_universe_loop.ps1                                              # 默认 800/组
#   .\backend\scripts\refresh_stock_universe_loop.ps1 -ShardSize 1000 -SleepFirst 60 -SleepRetry 30
#   .\backend\scripts\refresh_stock_universe_loop.ps1 -MaxRetryRounds 30                          # run-failed 最多跑 30 轮

param(
    [int]$ShardSize = 800,
    [int]$SleepFirst = 100,
    [int]$SleepRetry = 5,
    [int]$MaxRetryRounds = 30
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $ProjectRoot

Write-Host "=== refresh_stock_universe_loop.ps1 ===" -ForegroundColor Cyan
Write-Host "  project:        $ProjectRoot"
Write-Host "  shard_size:     $ShardSize (init --shard-size)"
Write-Host "  sleep_first:    ${SleepFirst}s (第一轮每组)"
Write-Host "  sleep_retry:    ${SleepRetry}s (run-failed 之间)"
Write-Host "  max_retry:      $MaxRetryRounds rounds (run-failed 循环上限)"
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
    Write-Host "[$($i + 2)/$($total + 2)] run group $groupId" -ForegroundColor Yellow
    Write-Host "============================================="
    python -m backend.scripts.refresh_stock_universe_sharded run --group $groupId
    Write-Host "[sleep ${SleepFirst}s]"
    Start-Sleep -Seconds $SleepFirst
}

# run-failed 循环 (跑到 failed 数量 = 0)
# 第一轮跑完到 run-failed 之间不 sleep
$failedFile = Join-Path $ProjectRoot "reference\stock-universe\_failed_codes.json"

for ($r = 1; $r -le $MaxRetryRounds; $r++) {
    # 读 failed 数量
    $count = -1
    if (Test-Path $failedFile) {
        try {
            $f = Get-Content $failedFile -Raw -Encoding UTF8 | ConvertFrom-Json
            $count = @($f.codes).Count
        } catch {
            $count = -1
        }
    } else {
        $count = 0
    }

    if ($count -le 0) {
        Write-Host ""
        Write-Host "============================================="
        Write-Host "[$($total + 2)/$($total + 2)] run-failed: 0 failed, skip" -ForegroundColor Green
        Write-Host "============================================="
        break
    }

    Write-Host ""
    Write-Host "============================================="
    Write-Host "[retry $r/$MaxRetryRounds] run-failed (当前 failed=$count)" -ForegroundColor Yellow
    Write-Host "============================================="
    python -m backend.scripts.refresh_stock_universe_sharded run-failed

    # 检查这一轮跑完是否还有 failed
    $countAfter = -1
    if (Test-Path $failedFile) {
        try {
            $f2 = Get-Content $failedFile -Raw -Encoding UTF8 | ConvertFrom-Json
            $countAfter = @($f2.codes).Count
        } catch {
            $countAfter = -1
        }
    } else {
        $countAfter = 0
    }

    if ($countAfter -le 0) {
        Write-Host "  -> retry $r done, all failed cleared" -ForegroundColor Green
        break
    }
    if ($countAfter -ge $count) {
        Write-Host "  -> retry $r done, failed not decreasing ($count -> $countAfter), sleep ${SleepRetry}s" -ForegroundColor DarkYellow
    } else {
        Write-Host "  -> retry $r done, $count -> $countAfter, sleep ${SleepRetry}s" -ForegroundColor DarkYellow
    }
    Start-Sleep -Seconds $SleepRetry
}

# aggregate
Write-Host ""
Write-Host "============================================="
Write-Host "[aggregate] 写 sectors_xxx_<n>.json + index.json" -ForegroundColor Yellow
Write-Host "============================================="
python -m backend.scripts.refresh_stock_universe_sharded aggregate
Write-Host ""
Write-Host "=== final status ===" -ForegroundColor Cyan
python -m backend.scripts.refresh_stock_universe_sharded status
