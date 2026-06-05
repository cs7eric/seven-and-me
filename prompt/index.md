# Prompt 索引

> 维护本目录所有 prompt 文件的清单。新增 / 删除 / 改用途时，**同步更新本表**。

## 约定

- **文件命名**：`{用途}_system.md` / `{用途}_user.md`（成对出现时），纯 system 用 `{用途}_system.md`
- **路径**：`Path(__file__).parent / "prompt" / "xxx.md"`，相对脚本位置，不依赖启动 cwd
- **模板语法**：用 Python `string.Template` 的 `$variable`（避开 `str.format` 与 JSON 示例 `{}` 冲突）
- **加载失败**：`FileNotFoundError` 带完整路径，方便定位
- **schema / 硬约束段**（如 JSON-only、字段闭合等）由调用方代码在加载后追加，**不要在 prompt 文件里重复写**

---

## 1. MP4 / 音频转写链路（`polisher.py`）

所有加载统一走 [`polisher.py:_load_prompt()`](file:///f:/dev-repo/mp4-to-word-new/polisher.py) 单行调用。

| 文件 | 用途 | 模板变量 | 喂给的方法 | 触发入口 |
| --- | --- | --- | --- | --- |
| [`ask_system.md`](file:///f:/dev-repo/mp4-to-word-new/prompt/ask_system.md) | Ask AI 问答 system | — | `ask_about_content()` | `POST /api/ask` & `POST /api/mp4-history/.../ask` |
| [`ask_user.md`](file:///f:/dev-repo/mp4-to-word-new/prompt/ask_user.md) | Ask AI 问答 user | `$polished_text` `$summary_text` `$question` | 同上 | 同上 |
| [`polish_system.md`](file:///f:/dev-repo/mp4-to-word-new/prompt/polish_system.md) | 文本润色 system | — | `polish()` | 转写 / 实时任务的润色阶段 |
| [`summarize_system.md`](file:///f:/dev-repo/mp4-to-word-new/prompt/summarize_system.md) | 结构化摘要 system | — | `summarize()` | 润色完成后的摘要阶段 |
| [`metadata_system.md`](file:///f:/dev-repo/mp4-to-word-new/prompt/metadata_system.md) | Markdown front matter system | — | `generate_post_metadata()` | 摘要完成后的标题 / 分类 / 标签生成 |
| [`metadata_user.md`](file:///f:/dev-repo/mp4-to-word-new/prompt/metadata_user.md) | Markdown front matter user | `$polished_text` `$summary_text` | 同上 | 同上 |

> `ask_about_content()` 返回 `qa_v1` JSON；`polish()` 返回纯文本；`summarize()` 返回结构化纯文本；`generate_post_metadata()` 返回 `{title, categories, tags}`。

---

## 2. 股票分析链路（`backend/services/stock/`）

每个 service 各自维护 `_prompt_text()`，负责「读文件 + 拼接硬约束段」。

| 文件 | 用途 | 加载位置 | 触发入口 | 状态 |
| --- | --- | --- | --- | --- |
| [`annotation.md`](file:///f:/dev-repo/mp4-to-word-new/prompt/annotation.md) | 当日分时 AI 逻辑分析 | [`application_analysis_service.py:29`](file:///f:/dev-repo/mp4-to-word-new/backend/services/stock/application_analysis_service.py#L29) | `POST /api/stock-chart/application-analysis`（分时 dialog 的「AI 逻辑分析」按钮） | ⚠️ **0 字节空文件**，需补 |
| [`short_term_daily.md`](file:///f:/dev-repo/mp4-to-word-new/prompt/short_term_daily.md) | 短趋势日线分析 | [`application_analysis_service.py:30`](file:///f:/dev-repo/mp4-to-word-new/backend/services/stock/application_analysis_service.py#L30) | 同 service 的短趋势分支 | ✅ |
| [`auction_analysis.md`](file:///f:/dev-repo/mp4-to-word-new/prompt/auction_analysis.md) | 集合竞价 AI 分析 | [`auction_ai_analysis_service.py:15`](file:///f:/dev-repo/mp4-to-word-new/backend/services/stock/auction_ai_analysis_service.py#L15) | 集合竞价 AI 分析定时任务 / API | ✅ |

---

## 维护 checklist

- [ ] 新增 prompt 文件 → 在本表对应分组加一行
- [ ] 删除 prompt 文件 → 在本表对应分组删一行
- [ ] 改用途 / 改方法 → 更新「喂给的方法」「触发入口」
- [ ] prompt 文件加新模板变量 → 在「模板变量」列登记
- [ ] prompt 跑空导致线上报错 → 状态标 ⚠️ 并在 commit message 说明
