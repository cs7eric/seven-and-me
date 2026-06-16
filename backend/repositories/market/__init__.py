"""DuckDB 读侧仓储层 (read-side repository).

所有函数返回 list[dict] / dict / 标量, 与 self_selected_repo 风格一致.
SQL 写在各模块文件里, 不抽取公共 ORM 层 — 简单直接, 每条查询都能一眼看懂.

输出 dict 形状与现有 StockKlineBar / 涨跌停 JSON 兼容, 方便后续 kline_service
接入时无缝替换.
"""
