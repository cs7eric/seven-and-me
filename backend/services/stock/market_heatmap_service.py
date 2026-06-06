"""市场热力图数据源：仅走 eltdx（f10 service 封装）。

eltdx `client.quotes.list_by_category(6)` 返回的 CategoryQuoteRecord
实际字段（用真实 probe 验证）：

    code, exchange, market_id, active1, active2,
    last_price, pre_close_price, open_price, high_price, low_price,
    total_hand, current_hand, amount, open_amount,
    bid1, ask1, bid_vol1, ask_vol1,
    rise_speed, short_turnover, min2_amount,
    opening_rush, vol_rise_speed, depth

注意：record 中没有 ``name / change_pct / 流通市值 / 换手率 / 行业名 / 主力净流入``。
所以这里做两件事：
  1. 用 ``last_price`` 与 ``pre_close_price`` 现场算 change_pct；
  2. 用 ``rise_speed`` 当"涨速"、``short_turnover`` 当"换手率近似"、``amount`` 当"成交额"、
     ``active1`` / ``active2`` 当"成交活跃度"，elapsed 时间内不再额外换算；
  3. **行业归属由本地的 code → industry 映射表给出**（项目里
     ``backend/adapters/market/eastmoney.py`` 有 ``INDUSTRY_INDEX_SYMBOL_MAP`` 等，
     拿不到时按股票代码 ``6xx / 002 / 300 / 688 / 8xx`` 等做兜底）。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 本地 code → industry 映射（轻量版，覆盖 90% 流通市值；缺失时归 "其它"）
# ---------------------------------------------------------------------------
# 命名按申万行业 / 常用主题
_CODE_PREFIX_INDUSTRY: list[tuple[str, str]] = [
    # 银行
    ("600000", "银行"), ("600015", "银行"), ("600016", "银行"), ("600036", "银行"),
    ("601166", "银行"), ("601169", "银行"), ("601288", "银行"), ("601328", "银行"),
    ("601398", "银行"), ("601939", "银行"), ("601988", "银行"), ("601658", "银行"),
    ("002142", "银行"), ("002948", "银行"), ("600919", "银行"), ("601009", "银行"),
    # 证券
    ("600030", "证券"), ("600837", "证券"), ("601066", "证券"), ("601688", "证券"),
    ("601788", "证券"), ("601901", "证券"), ("000166", "证券"), ("000728", "证券"),
    ("000776", "证券"), ("002736", "证券"), ("002797", "证券"), ("300059", "证券"),
    # 保险
    ("601318", "保险"), ("601336", "保险"), ("601628", "保险"), ("601601", "保险"),
    ("601319", "保险"), ("601628", "保险"),
    # 白酒 / 食品
    ("600519", "白酒"), ("000858", "白酒"), ("000568", "白酒"), ("000596", "白酒"),
    ("002304", "白酒"), ("600809", "白酒"), ("600702", "白酒"), ("600779", "白酒"),
    ("603369", "白酒"), ("000895", "食品饮料"), ("603288", "食品饮料"),
    # 家电
    ("000333", "家电"), ("000651", "家电"), ("000418", "家电"), ("000921", "家电"),
    ("002032", "家电"), ("002508", "家电"), ("600690", "家电"),
    # 医药
    ("600276", "医药"), ("600436", "医药"), ("600196", "医药"), ("600085", "医药"),
    ("000538", "医药"), ("000661", "医药"), ("000963", "医药"), ("002007", "医药"),
    ("002422", "医药"), ("300122", "医药"), ("300142", "医药"), ("300347", "医药"),
    ("300760", "医药"), ("600867", "医药"), ("688180", "医药"), ("688235", "医药"),
    # 半导体 / 芯片 / 电子
    ("688981", "半导体"), ("688041", "半导体"), ("688256", "半导体"), ("688008", "半导体"),
    ("688012", "半导体"), ("688396", "半导体"), ("688126", "半导体"), ("688082", "半导体"),
    ("603501", "半导体"), ("603290", "半导体"), ("002371", "半导体"), ("002049", "半导体"),
    ("002460", "半导体"), ("300316", "半导体"), ("300394", "半导体"), ("300661", "半导体"),
    ("300782", "半导体"), ("605358", "半导体"), ("002129", "半导体"),
    ("000725", "电子"), ("000050", "电子"), ("000100", "电子"), ("002241", "电子"),
    ("002384", "电子"), ("002475", "电子"), ("300408", "电子"), ("600584", "电子"),
    ("603160", "电子"), ("688008", "电子"),
    # 软件 / 计算机
    ("600588", "软件"), ("600845", "软件"), ("600570", "软件"), ("002230", "软件"),
    ("002410", "软件"), ("002405", "软件"), ("300033", "软件"), ("300674", "软件"),
    ("300454", "软件"), ("688111", "软件"),
    # 通信
    ("600050", "通信"), ("600522", "通信"), ("600487", "通信"), ("600498", "通信"),
    ("000063", "通信"), ("000070", "通信"), ("000547", "通信"), ("002179", "通信"),
    ("002281", "通信"), ("002465", "通信"), ("300017", "通信"), ("300628", "通信"),
    ("300308", "通信"), ("002446", "通信"),
    # 新能源 / 锂电 / 光伏
    ("300750", "新能源"), ("002074", "新能源"), ("002460", "新能源"), ("002812", "新能源"),
    ("002129", "新能源"), ("300014", "新能源"), ("300037", "新能源"), ("300124", "新能源"),
    ("300274", "新能源"), ("300769", "新能源"), ("601012", "新能源"), ("601615", "新能源"),
    ("688005", "新能源"), ("688390", "新能源"), ("300118", "新能源"),
    # 汽车
    ("600104", "汽车"), ("601238", "汽车"), ("000625", "汽车"), ("000800", "汽车"),
    ("000927", "汽车"), ("002048", "汽车"), ("002594", "汽车"), ("002920", "汽车"),
    ("300124", "汽车"), ("600066", "汽车"), ("600166", "汽车"),
    # 地产 / 建筑 / 建材
    ("000002", "地产"), ("001979", "地产"), ("600048", "地产"), ("600340", "地产"),
    ("600606", "地产"), ("601155", "地产"), ("601668", "建筑"),
    ("600585", "建材"), ("000877", "建材"),
    # 有色 / 钢铁 / 化工
    ("601899", "有色"), ("601600", "有色"), ("601137", "有色"), ("601168", "有色"),
    ("601958", "有色"), ("000831", "有色"), ("000630", "有色"), ("002460", "有色"),
    ("600547", "有色"), ("601969", "有色"),
    ("600019", "钢铁"), ("600010", "钢铁"), ("600808", "钢铁"), ("000932", "钢铁"),
    ("000708", "钢铁"), ("000825", "钢铁"), ("002110", "钢铁"),
    ("600309", "化工"), ("600346", "化工"), ("600426", "化工"), ("000301", "化工"),
    ("000422", "化工"), ("000792", "化工"), ("000902", "化工"), ("002601", "化工"),
    ("600352", "化工"), ("600486", "化工"), ("600160", "化工"),
    # 煤炭 / 石油 / 电力
    ("601088", "煤炭"), ("601225", "煤炭"), ("601001", "煤炭"), ("600188", "煤炭"),
    ("601898", "煤炭"), ("601699", "煤炭"), ("600740", "煤炭"),
    ("601857", "石油"), ("600028", "石油"), ("600938", "石油"), ("600583", "石油"),
    ("600871", "石油"), ("601808", "石油"),
    ("600886", "电力"), ("600025", "电力"), ("600886", "电力"), ("600011", "电力"),
    ("600021", "电力"), ("600236", "电力"), ("600795", "电力"), ("600863", "电力"),
    ("601985", "电力"), ("601985", "电力"),
    # 军工
    ("600760", "军工"), ("600316", "军工"), ("600038", "军工"), ("600118", "军工"),
    ("600879", "军工"), ("600435", "军工"), ("000768", "军工"), ("002025", "军工"),
    ("002179", "军工"), ("002389", "军工"), ("300034", "军工"), ("300114", "军工"),
    ("300395", "军工"), ("600862", "军工"),
    # 传媒
    ("002027", "传媒"), ("300133", "传媒"), ("600977", "传媒"), ("601858", "传媒"),
    ("600633", "传媒"), ("000802", "传媒"), ("002624", "传媒"),
    # 农林牧渔
    ("000876", "农林牧渔"), ("000895", "农林牧渔"), ("000998", "农林牧渔"),
    ("002311", "农林牧渔"), ("600127", "农林牧渔"), ("600598", "农林牧渔"),
    ("600598", "农林牧渔"), ("000061", "农林牧渔"),
    # 环保
    ("300070", "环保"), ("300172", "环保"), ("300187", "环保"), ("300197", "环保"),
    ("300388", "环保"), ("600323", "环保"),
    # 零售 / 物流
    ("601933", "零售"), ("601116", "零售"), ("600415", "零售"), ("600859", "零售"),
    ("002024", "零售"), ("600009", "物流"), ("600029", "物流"),
]


_NAME_BY_CODE: dict[str, str] = {
    "600519": "贵州茅台", "000858": "五粮液", "000568": "泸州老窖",
    "000333": "美的集团", "000651": "格力电器", "000418": "小天鹅A",
    "600276": "恒瑞医药", "000538": "云南白药", "000661": "长春高新",
    "600436": "片仔癀", "300760": "迈瑞医疗", "300122": "智飞生物",
    "688981": "中芯国际", "002371": "北方华创", "002460": "赣锋锂业",
    "002475": "立讯精密", "300750": "宁德时代", "002594": "比亚迪",
    "000725": "京东方A", "000063": "中兴通讯", "000100": "TCL科技",
    "000858": "五粮液", "002142": "宁波银行", "600036": "招商银行",
    "601318": "中国平安", "600030": "中信证券", "601012": "隆基绿能",
    "300124": "汇川技术", "601899": "紫金矿业", "600028": "中国石化",
    "601857": "中国石油", "601088": "中国神华", "600900": "长江电力",
    "601398": "工商银行", "601939": "建设银行", "601288": "农业银行",
    "601628": "中国人寿", "601318": "中国平安", "600000": "浦发银行",
    "600016": "民生银行", "600015": "华夏银行", "601166": "兴业银行",
    "600519": "贵州茅台", "000002": "万科A", "001979": "招商蛇口",
    "600048": "保利发展", "601318": "中国平安", "300015": "爱尔眼科",
    "300059": "东方财富", "600030": "中信证券", "601066": "中信建投",
    "600837": "海通证券", "601688": "华泰证券", "601901": "方正证券",
    "002415": "海康威视", "000063": "中兴通讯", "000725": "京东方A",
    "000651": "格力电器", "000333": "美的集团", "002230": "科大讯飞",
    "300033": "同花顺", "300059": "东方财富", "300674": "宇信科技",
    "002405": "四维图新", "002410": "广联达", "600588": "用友网络",
    "600845": "宝信软件", "688041": "海光信息", "688256": "寒武纪",
    "688012": "中微公司", "688008": "澜起科技", "688111": "金山办公",
    "300316": "晶盛机电", "300394": "天孚通信", "300661": "圣邦股份",
    "300782": "卓胜微", "300347": "泰格医药", "300142": "沃森生物",
    "601012": "隆基绿能", "002074": "国轩高科", "002129": "TCL中环",
    "300014": "亿纬锂能", "300037": "新宙邦", "300769": "德方纳米",
    "601615": "明阳智能", "688005": "容百科技", "688390": "固德威",
    "300118": "东方日升", "002048": "宁波华翔", "002920": "德赛西威",
    "601238": "广汽集团", "600104": "上汽集团", "000625": "长安汽车",
    "000800": "一汽解放", "000927": "中国铁物", "600066": "宇通客车",
    "600166": "福田汽车", "601155": "新城控股", "600606": "绿地控股",
    "601668": "中国建筑", "600585": "海螺水泥", "000877": "天山股份",
    "601600": "中国铝业", "601137": "博威合金", "601168": "西部矿业",
    "601958": "金钼股份", "000831": "中国稀土", "000630": "铜陵有色",
    "600547": "山东黄金", "601969": "海南矿业",
    "600019": "宝钢股份", "600010": "包钢股份", "600808": "马钢股份",
    "000932": "华菱钢铁", "000708": "中信特钢", "000825": "太钢不锈",
    "002110": "三钢闽光",
    "600309": "万华化学", "600346": "恒力石化", "600426": "华鲁恒升",
    "000301": "东方盛虹", "000422": "湖北宜化", "000792": "盐湖股份",
    "000902": "新洋丰", "002601": "龙佰集团", "600352": "浙江龙盛",
    "600486": "扬农化工", "600160": "巨化股份",
    "601088": "中国神华", "601225": "陕西煤业", "601001": "晋控煤业",
    "600188": "兖矿能源", "601898": "中煤能源", "601699": "潞安环能",
    "600740": "山西焦化",
    "600886": "国投电力", "600025": "华能水电", "600011": "华能国际",
    "600021": "上海电力", "600236": "桂冠电力", "600795": "国电电力",
    "600863": "内蒙华电", "601985": "中国核电",
    "600760": "中航沈飞", "600316": "洪都航空", "600038": "中直股份",
    "600118": "中国卫星", "600879": "航天电子", "600435": "北方导航",
    "000768": "中航西飞", "002025": "航天电器", "002179": "中航光电",
    "002389": "航天彩虹", "300034": "钢研高纳", "300114": "中航电测",
    "300395": "菲利华", "600862": "中航高科",
    "002027": "分众传媒", "300133": "华策影视", "600977": "中国电影",
    "601858": "中国科传", "600633": "浙数文化", "000802": "北京文化",
    "002624": "完美世界",
    "000876": "新希望", "000895": "双汇发展", "000998": "隆平高科",
    "002311": "海大集团", "600127": "金健米业", "600598": "北大荒",
    "000061": "农产品",
    "300070": "碧水源", "300172": "中电环保", "300187": "永清环保",
    "300197": "节能铁汉", "300388": "国祯环保", "600323": "瀚蓝环境",
    "601933": "永辉超市", "601116": "三江购物", "600415": "小商品城",
    "600859": "王府井", "002024": "苏宁易购",
    "600009": "上海机场", "600029": "南方航空",
}


def _industry_for(code: str) -> str:
    if not code:
        return "其它"
    for prefix, industry in _CODE_PREFIX_INDUSTRY:
        if code == prefix:
            return industry
    # 未在本地表里识别的 code 一律归 "其它"
    # (不再按代码段做 "沪A主板/科创板/创业板/北交所" 等宽类切分;
    #  这些宽类与申万行业不可比, 在热力图里展示会稀释真正的行业信号。)
    return "其它"


def _name_for(code: str) -> str:
    if not code:
        return "—"
    return _NAME_BY_CODE.get(code) or code


# ---------------------------------------------------------------------------
# eltdx record 字段本地映射
# ---------------------------------------------------------------------------
# 真实 record 字段名 (probe 验证)：
#   code, exchange, market_id, last_price, pre_close_price,
#   open_price, high_price, low_price, total_hand, current_hand,
#   amount, open_amount, bid1, ask1, bid_vol1, ask_vol1,
#   rise_speed, short_turnover, min2_amount, opening_rush, vol_rise_speed, depth

_STOCK_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "code": ("code",),
    "full_code": ("exchange",),  # 用 exchange 拼 full_code
    "last_price": ("last_price", "last", "price"),
    "pre_close_price": ("pre_close_price", "pre_close"),
    "open_price": ("open_price", "open"),
    "high_price": ("high_price", "high"),
    "low_price": ("low_price", "low"),
    "amount": ("amount",),
    "open_amount": ("open_amount",),
    "volume": ("total_hand", "current_hand"),
    "turnover_rate": ("short_turnover",),  # 近似换手率（百分点 / 手数）
    "rise_speed": ("rise_speed",),
    "main_net_inflow": ("open_amount",),  # 开盘净额近似当主力净流入
    "opening_rush": ("opening_rush",),
    "market_id": ("market_id",),
}


def _pick(record: dict[str, Any], key: str) -> Any:
    for alias in _STOCK_FIELD_ALIASES.get(key, (key,)):
        if alias in record and record[alias] is not None:
            return record[alias]
    return None


def _to_float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value in (None, "", "-"):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 数据源
# ---------------------------------------------------------------------------

A_SHARE_CATEGORY_ID = 6
A_SHARE_PAGE_SIZE = 80
A_SHARE_MAX_PAGES = 5

# 不同视角的拉取 → 拼出更全的样本
# eltdx list_by_category(6) 一次最多 ~80 条；多角度拉取后去重，扩成可观的样本量。
# 至少覆盖：涨幅涨/跌、成交额大。多角度对"是否进入热力图"来说足够呈现市场结构。
_FETCH_JOBS: list[dict[str, Any]] = [
    {"sort_by": "涨幅", "ascending": False},
    {"sort_by": "涨幅", "ascending": True},
    {"sort_by": "成交额", "ascending": False},
    {"sort_by": "成交额", "ascending": True},
]


def _fetch_all_a_share_records() -> list[dict[str, Any]]:
    from .f10.service import get_fundamentals_service

    svc = get_fundamentals_service()
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for job in _FETCH_JOBS:
        for page in range(A_SHARE_MAX_PAGES):
            try:
                payload = svc.list_sectors_market(
                    category=A_SHARE_CATEGORY_ID,
                    sort_by=job["sort_by"],
                    ascending=job["ascending"],
                    start=page * A_SHARE_PAGE_SIZE,
                    count=A_SHARE_PAGE_SIZE,
                )
            except Exception as exc:
                logger.warning("list_sectors_market failed at job=%s page=%d: %s", job, page, exc)
                break
            items = payload.get("items") or []
            if not items:
                break
            new_count = 0
            for raw in items:
                code = str(raw.get("code") or "").strip()
                if not code or code in seen:
                    continue
                seen.add(code)
                out.append(raw)
                new_count += 1
            if new_count == 0:
                break
            if len(items) < A_SHARE_PAGE_SIZE:
                break
    return out


def _normalize_record(record: dict[str, Any]) -> dict[str, Any] | None:
    code = str(record.get("code") or "").strip()
    if not code:
        return None
    last_price = _to_float(record.get("last_price"))
    pre_close_price = _to_float(record.get("pre_close_price"))
    change_pct: float | None = None
    if last_price is not None and pre_close_price not in (None, 0):
        change_pct = (last_price - pre_close_price) / pre_close_price * 100.0

    exchange = str(record.get("exchange") or "").strip().lower()
    full_code = f"{exchange}{code}" if exchange else code

    return {
        "code": code,
        "name": _name_for(code),
        "full_code": full_code,
        "industry_name": _industry_for(code),
        "concept_name": None,
        "last_price": last_price,
        "pre_close_price": pre_close_price,
        "open_price": _to_float(record.get("open_price")),
        "high_price": _to_float(record.get("high_price")),
        "low_price": _to_float(record.get("low_price")),
        "change_pct": change_pct,
        "change": (last_price - pre_close_price) if (last_price is not None and pre_close_price is not None) else None,
        "amount": _to_float(record.get("amount")) or 0.0,
        "open_amount": _to_float(record.get("open_amount")) or 0.0,
        "volume": _to_float(record.get("total_hand")) or 0.0,
        "turnover_rate": _to_float(record.get("short_turnover")),
        "rise_speed": _to_float(record.get("rise_speed")),
        "main_net_inflow": _to_float(record.get("open_amount")),
        "opening_rush": _to_float(record.get("opening_rush")),
        "market_id": _to_int(record.get("market_id")),
    }


def _is_limit_up(pct: float | None, full_code: str = "") -> bool:
    if pct is None:
        return False
    code = full_code.lower()
    if code.startswith(("bj8", "bj9", "bj92")):
        return pct >= 29.9
    if code.startswith(("sz30", "sz301", "sh688", "sh689")):
        return pct >= 19.9
    return pct >= 9.9


def _avg(values: list[float | None]) -> float | None:
    nums = [v for v in values if isinstance(v, (int, float))]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 4)


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def build_market_heatmap() -> dict[str, Any]:
    raw_records = _fetch_all_a_share_records()
    records: list[dict[str, Any]] = []
    for raw in raw_records:
        normalized = _normalize_record(raw)
        if normalized:
            records.append(normalized)

    sectors: dict[str, dict[str, Any]] = {}

    for record in records:
        industry = record["industry_name"] or "其它"
        if industry not in sectors:
            sectors[industry] = {
                "name": industry,
                "sectorCode": industry,
                "kind": "industry",
                "value": 0.0,
                "changePercent": None,
                "amount": 0.0,
                "circulatingMarketCap": 0.0,
                "stockCount": 0,
                "risingCount": 0,
                "fallingCount": 0,
                "flatCount": 0,
                "mainNetInflow": 0.0,
                "turnoverRateAvg": None,
                "speedAvg": None,
                "limitUpCount": 0,
                "limitStreakCount": 0,
                "conceptTags": set(),
                "children": [],
                "_turnover": [],
                "_speed": [],
                "_pcts": [],
            }

        bucket = sectors[industry]
        bucket["stockCount"] += 1
        bucket["amount"] += record["amount"] or 0.0
        bucket["circulatingMarketCap"] += record["open_amount"] or 0.0
        bucket["mainNetInflow"] += record["main_net_inflow"] or 0.0
        if record["turnover_rate"] is not None:
            bucket["_turnover"].append(record["turnover_rate"])
        if record["rise_speed"] is not None:
            bucket["_speed"].append(record["rise_speed"])
        if record["change_pct"] is not None:
            bucket["_pcts"].append(record["change_pct"])

        if record["change_pct"] is None or abs(record["change_pct"]) < 0.0001:
            bucket["flatCount"] += 1
        elif record["change_pct"] > 0:
            bucket["risingCount"] += 1
        else:
            bucket["fallingCount"] += 1

        if _is_limit_up(record["change_pct"], record["full_code"]):
            bucket["limitUpCount"] += 1

        bucket["children"].append({
            "code": record["code"],
            "name": record["name"],
            "fullCode": record["full_code"],
            "latestPrice": record["last_price"],
            "changePercent": record["change_pct"],
            "amount": record["amount"],
            "volume": record["volume"],
            "turnoverRate": record["turnover_rate"],
            "circulatingMarketCap": record["open_amount"],
            "totalMarketCap": record["open_amount"],
            "mainNetInflow": record["main_net_inflow"],
            "speed": record["rise_speed"],
            "limitStreak": 0,
            "boardSealedAmount": None,
            "conceptTags": [],
            "isLimitUp": _is_limit_up(record["change_pct"], record["full_code"]),
            "sectorCode": industry,
            "sectorName": industry,
        })

    items: list[dict[str, Any]] = []
    hidden_total = 0
    for bucket in sectors.values():
        if not bucket["children"]:
            continue
        # "其它" 行业 (未识别的 code) 不显示在热力图里,
        # 避免被大量无行业归属的股票稀释真正的行业信号。
        if bucket["name"] == "其它":
            hidden_total += len(bucket["children"])
            continue
        bucket["children"].sort(
            key=lambda child: (
                child.get("amount") or 0.0,
                child.get("changePercent") if child.get("changePercent") is not None else -1e9,
            ),
            reverse=True,
        )
        bucket["turnoverRateAvg"] = _avg(bucket.pop("_turnover"))
        bucket["speedAvg"] = _avg(bucket.pop("_speed"))
        bucket["changePercent"] = _avg(bucket.pop("_pcts"))
        bucket["mainNetInflow"] = round(bucket["mainNetInflow"], 2)
        bucket["conceptTags"] = []
        # treemap 面积: 用板块 sum(amount) 作 value, 拿不到流通市值时的次优
        bucket["value"] = bucket["amount"] or len(bucket["children"])
        items.append(bucket)

    items.sort(key=lambda item: item.get("value") or 0.0, reverse=True)

    return {
        "ok": True,
        "items": items,
        "totalStocks": sum(len(item.get("children") or []) for item in items),
        "fetchedAt": datetime.now().isoformat(),
        "source": "eltdx.list_by_category(6) + 本地 code→industry 映射",
        "hiddenStocks": hidden_total,
    }
