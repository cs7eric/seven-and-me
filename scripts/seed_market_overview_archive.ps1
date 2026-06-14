# 一次性脚本: 把用户在网上搜集的 50 个交易日的 eltdx 全A数据
# (成交额 / 涨跌家数 / 涨停跌停家数) 写入 reference/market-overview/archive/{YYYYMMDD}.json
#
# 字段合并策略 (跟 eltdx service 的 _save_overview_to_archive 一致):
#   - 现有文件已含 fund-flow 字段 (mainNetInflow 等), 不动
#   - 只更新 eltdx_fields: totalAmount / risingCount / fallingCount / flatCount /
#                         limitUpCount / limitDownCount (stockCount 用户没给, 跳过)
#   - 2026 年的 MM/DD 前缀
#   - "--" 子市场值 → 该日 flatCount 写 null (其他列仍可算)

$ErrorActionPreference = "Stop"
$repoRoot = (Get-Location).Path
$archiveDir = Join-Path $repoRoot "reference\market-overview\archive"

if (-not (Test-Path $archiveDir)) {
    throw "archive 目录不存在: $archiveDir"
}

# 用户数据: (date_md, limitUp, limitDown, totalAmountYi, sh_up, sh_flat, sh_down, sz_up, sz_flat, sz_down, bj_up, bj_flat, bj_down)
# "--" 用 $null 占位
$rows = @(
    @{d="06/12"; lu=105;    ld=23;     amt=32362.99; hu=1669; hf=29;   hd=616;  zu=2039; zf=58;  zd=797;  bu=215; bf=3;    bd=102  }
    @{d="06/11"; lu=79;     ld=55;     amt=25751.42; hu=676;  hf=36;   hd=1602; zu=672;  zf=50;  zd=2171; bu=22;  bf=2;    bd=296  }
    @{d="06/10"; lu=76;     ld=74;     amt=26443.76; hu=809;  hf=37;   hd=1468; zu=710;  zf=49;  zd=2134; bu=37;  bf=2;    bd=280  }
    @{d="06/09"; lu=144;    ld=19;     amt=26669.21; hu=1322; hf=63;   hd=930;  zu=1894; zf=87;  zd=912;  bu=106; bf=6;    bd=207  }
    @{d="06/08"; lu=64;     ld=56;     amt=28236.44; hu=307;  hf=10;   hd=1998; zu=358;  zf=19;  zd=2515; bu=234; bf=7;    bd=78   }
    @{d="06/05"; lu=88;     ld=18;     amt=31010.72; hu=1259; hf=60;   hd=996;  zu=1723; zf=74;  zd=1095; bu=295; bf=1;    bd=22   }
    @{d="06/04"; lu=92;     ld=34;     amt=27794.17; hu=571;  hf=26;   hd=1718; zu=723;  zf=32;  zd=2137; bu=50;  bf=1;    bd=266  }
    @{d="06/03"; lu=82;     ld=30;     amt=31534.20; hu=793;  hf=28;   hd=1494; zu=851;  zf=51;  zd=1990; bu=69;  bf=5;    bd=243  }
    @{d="06/02"; lu=98;     ld=18;     amt=28132.27; hu=639;  hf=36;   hd=1640; zu=734;  zf=57;  zd=2102; bu=170; bf=13;   bd=134  }
    @{d="06/01"; lu=170;    ld=25;     amt=28969.74; hu=1525; hf=28;   hd=762;  zu=1988; zf=38;  zd=867;  bu=263; bf=1;    bd=53   }
    @{d="05/29"; lu=71;     ld=64;     amt=33412.52; hu=746;  hf=41;   hd=1528; zu=700;  zf=50;  zd=2144; bu=96;  bf=9;    bd=212  }
    @{d="05/28"; lu=127;    ld=13;     amt=29875.98; hu=1106; hf=63;   hd=1146; zu=1642; zf=76;  zd=1175; bu=270; bf=2;    bd=44   }
    @{d="05/27"; lu=62;     ld=35;     amt=32602.50; hu=441;  hf=34;   hd=1840; zu=494;  zf=26;  zd=2373; bu=39;  bf=1;    bd=276  }
    @{d="05/26"; lu=68;     ld=37;     amt=32646.41; hu=628;  hf=44;   hd=1642; zu=686;  zf=38;  zd=2169; bu=40;  bf=4;    bd=271  }
    @{d="05/25"; lu=129;    ld=27;     amt=32272.34; hu=1014; hf=46;   hd=1254; zu=1107; zf=64;  zd=1722; bu=60;  bf=6;    bd=249  }
    @{d="05/22"; lu=138;    ld=20;     amt=29249.32; hu=1572; hf=63;   hd=679;  zu=2165; zf=67;  zd=661;  bu=132; bf=14;   bd=169  }
    @{d="05/21"; lu=37;     ld=69;     amt=34733.50; hu=333;  hf=21;   hd=1959; zu=340;  zf=22;  zd=2530; bu=29;  bf=4;    bd=281  }
    @{d="05/20"; lu=71;     ld=41;     amt=29767.56; hu=773;  hf=36;   hd=1504; zu=826;  zf=38;  zd=2028; bu=39;  bf=3;    bd=272  }
    @{d="05/19"; lu=123;    ld=26;     amt=29092.25; hu=1537; hf=52;   hd=724;  zu=1819; zf=83;  zd=990;  bu=252; bf=2;    bd=60   }
    @{d="05/18"; lu=102;    ld=55;     amt=29174.50; hu=1000; hf=69;   hd=1244; zu=1311; zf=66;  zd=1515; bu=64;  bf=6;    bd=244  }
    @{d="05/15"; lu=71;     ld=46;     amt=31343.84; hu=588;  hf=40;   hd=1685; zu=794;  zf=51;  zd=2046; bu=104; bf=8;    bd=201  }
    @{d="05/14"; lu=82;     ld=48;     amt=33884.18; hu=463;  hf=38;   hd=1812; zu=547;  zf=40;  zd=2303; bu=37;  bf=3;    bd=272  }
    @{d="05/13"; lu=147;    ld=17;     amt=32645.23; hu=1283; hf=76;   hd=954;  zu=1753; zf=84;  zd=1054; bu=179; bf=7;    bd=126  }
    @{d="05/12"; lu=94;     ld=34;     amt=32700.03; hu=613;  hf=40;   hd=1660; zu=663;  zf=41;  zd=2186; bu=103; bf=7;    bd=202  }
    @{d="05/11"; lu=136;    ld=30;     amt=35657.05; hu=1348; hf=70;   hd=895;  zu=1682; zf=79;  zd=1129; bu=91;  bf=6;    bd=215  }
    @{d="05/08"; lu=126;    ld=33;     amt=30759.30; hu=1425; hf=67;   hd=820;  zu=1950; zf=77;  zd=862;  bu=262; bf=4;    bd=46   }
    @{d="05/07"; lu=128;    ld=55;     amt=31686.11; hu=1420; hf=70;   hd=822;  zu=1826; zf=85;  zd=979;  bu=274; bf=7;    bd=31   }
    @{d="05/06"; lu=126;    ld=64;     amt=32469.71; hu=1552; hf=49;   hd=711;  zu=2095; zf=82;  zd=713;  bu=242; bf=11;   bd=58   }
    @{d="04/30"; lu=98;     ld=55;     amt=27595.40; hu=1148; hf=82;   hd=1082; zu=1523; zf=86;  zd=1280; bu=207; bf=5;    bd=99   }
    @{d="04/29"; lu=121;    ld=42;     amt=26090.92; hu=1632; hf=59;   hd=621;  zu=2099; zf=72;  zd=717;  bu=242; bf=4;    bd=65   }
    @{d="04/28"; lu=77;     ld=54;     amt=25508.35; hu=785;  hf=69;   hd=1458; zu=876;  zf=61;  zd=1951; bu=37;  bf=$null;bd=273  }
    @{d="04/27"; lu=85;     ld=54;     amt=26051.48; hu=1345; hf=59;   hd=908;  zu=1837; zf=59;  zd=992;  bu=102; bf=3;    bd=205  }
    @{d="04/24"; lu=68;     ld=40;     amt=26579.89; hu=865;  hf=62;   hd=1386; zu=1130; zf=60;  zd=1699; bu=41;  bf=1;    bd=267  }
    @{d="04/23"; lu=59;     ld=31;     amt=28235.57; hu=668;  hf=57;   hd=1587; zu=636;  zf=42;  zd=2210; bu=26;  bf=1;    bd=281  }
    @{d="04/22"; lu=63;     ld=17;     amt=25790.92; hu=1188; hf=80;   hd=1044; zu=1470; zf=72;  zd=1346; bu=262; bf=3;    bd=43   }
    @{d="04/21"; lu=65;     ld=19;     amt=24268.39; hu=958;  hf=60;   hd=1294; zu=958;  zf=68;  zd=1863; bu=33;  bf=$null;bd=275  }
    @{d="04/20"; lu=93;     ld=17;     amt=26066.90; hu=1343; hf=82;   hd=886;  zu=1854; zf=99;  zd=936;  bu=227; bf=5;    bd=76   }
    @{d="04/17"; lu=77;     ld=7;      amt=24531.06; hu=944;  hf=55;   hd=1312; zu=1147; zf=69;  zd=1672; bu=305; bf=$null;bd=2    }
    @{d="04/16"; lu=88;     ld=10;     amt=23551.48; hu=1729; hf=66;   hd=516;  zu=2336; zf=63;  zd=488;  bu=228; bf=11;   bd=68   }
    @{d="04/15"; lu=68;     ld=15;     amt=24296.64; hu=850;  hf=56;   hd=1404; zu=852;  zf=51;  zd=1983; bu=139; bf=13;   bd=154  }
    @{d="04/14"; lu=73;     ld=11;     amt=23969.72; hu=1507; hf=81;   hd=722;  zu=2009; zf=94;  zd=783;  bu=207; bf=10;   bd=89   }
    @{d="04/13"; lu=86;     ld=10;     amt=21632.60; hu=974;  hf=70;   hd=1266; zu=1343; zf=89;  zd=1454; bu=61;  bf=5;    bd=240  }
    @{d="04/10"; lu=78;     ld=13;     amt=23377.70; hu=1608; hf=52;   hd=650;  zu=2101; zf=75;  zd=712;  bu=268; bf=2;    bd=35   }
    @{d="04/09"; lu=64;     ld=14;     amt=21474.98; hu=505;  hf=31;   hd=1773; zu=610;  zf=29;  zd=2247; bu=25;  bf=$null;bd=279  }
    @{d="04/08"; lu=135;    ld=12;     amt=24510.01; hu=2142; hf=12;   hd=155;  zu=2736; zf=13;  zd=138;  bu=296; bf=$null;bd=8    }
    @{d="04/07"; lu=101;    ld=18;     amt=16237.80; hu=1568; hf=46;   hd=694;  zu=2236; zf=42;  zd=608;  bu=173; bf=6;    bd=124  }
    @{d="04/03"; lu=39;     ld=46;     amt=16690.95; hu=346;  hf=19;   hd=1943; zu=352;  zf=17;  zd=2518; bu=18;  bf=$null;bd=285  }
    @{d="04/02"; lu=32;     ld=20;     amt=18579.87; hu=438;  hf=35;   hd=1835; zu=456;  zf=28;  zd=2402; bu=158; bf=4;    bd=141  }
    @{d="04/01"; lu=66;     ld=15;     amt=20251.23; hu=1849; hf=65;   hd=394;  zu=2379; zf=48;  zd=459;  bu=267; bf=2;    bd=34   }
    @{d="03/31"; lu=59;     ld=19;     amt=20061.24; hu=443;  hf=44;   hd=1821; zu=460;  zf=54;  zd=2371; bu=108; bf=9;    bd=186  }
)

# eltdx service 的字段集 (跟 _save_overview_to_archive 一致)
$eltdxFields = @("totalAmount", "totalVolume", "risingCount", "fallingCount",
                 "flatCount", "limitUpCount", "limitDownCount", "stockCount")

$updated = 0
$skipped = 0

foreach ($r in $rows) {
    $md = $r.d
    $mm = $md.Split("/")[0]
    $dd = $md.Split("/")[1]
    $yyyymmdd = "2026$mm$dd"
    $date = "2026-$mm-$dd"
    $archPath = Join-Path $archiveDir "$yyyymmdd.json"

    if (-not (Test-Path $archPath)) {
        Write-Host "  SKIP: $date - archive file 不存在 ($archPath)"
        $skipped++
        continue
    }

    # 读现有 (含 fund-flow 字段)
    $existing = Get-Content $archPath -Raw -Encoding UTF8 | ConvertFrom-Json

    # 算 全A 汇总
    $rising  = $r.hu + $r.zu + $r.bu
    $falling = $r.hd + $r.zd + $r.bd
    $flat    = if ($null -eq $r.hf -or $null -eq $r.zf -or $null -eq $r.bf) { $null } else { $r.hf + $r.zf + $r.bf }

    # 用 PSCustomObject 临时构造, 写回时序列化顺序由 ConvertTo-Json 决定
    $existing.totalAmount    = [double]$r.amt
    $existing.risingCount    = [int]$rising
    $existing.fallingCount   = [int]$falling
    if ($null -eq $flat) {
        $existing.flatCount = $null
    } else {
        $existing.flatCount = [int]$flat
    }
    $existing.limitUpCount   = [int]$r.lu
    $existing.limitDownCount = [int]$r.ld
    # stockCount 用户没给 → 保持原值 (不写覆盖)
    # totalVolume 用户没给 → 保持原值

    # 写回 (保持 2 空格缩进, UTF-8 无 BOM)
    $json = $existing | ConvertTo-Json -Depth 10
    Set-Content -Path $archPath -Value $json -Encoding UTF8

    $flatTxt = if ($null -eq $flat) { "null" } else { "$flat" }
    Write-Host "  OK: $date  rising=$rising falling=$falling flat=$flatTxt lu=$($r.lu) ld=$($r.ld) amt=$($r.amt)"
    $updated++
}

Write-Host ""
Write-Host "完成: 更新 $updated 个文件, 跳过 $skipped 个."
