import json
import os
import re
import requests
from typing import Callable, Optional


class TextPolisher:
    """AI 润色模块 - 基于 MiniMax API"""

    BASE_URL = "https://api.minimaxi.com"

    def __init__(self, api_key: Optional[str] = None, group_id: Optional[str] = None):
        self.api_key = api_key or os.getenv("MINIMAX_API_KEY")
        self.group_id = group_id or os.getenv("MINIMAX_GROUP_ID")

        if not self.api_key:
            raise ValueError("请设置 MINIMAX_API_KEY")
        if not self.group_id:
            raise ValueError("请设置 MINIMAX_GROUP_ID")

        print(f"[Polisher] API Key: {self.api_key[:12]}...")

    def _stream_chat_completion(
        self,
        system_prompt: str,
        user_text: str,
        timeout: int = 120,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> str:
        """调用 MiniMax 流式接口，并在每次有增量时回调当前完整文本。

        MiniMax 的流式返回有时会在 delta 增量之后，再给一次完整 message.content。
        如果把 delta.content 和 message.content 都直接拼接，就会得到：
        `{...json...}{...json...}` 或 ```json...``````json...```。
        这里的规则是：优先使用 delta 增量；只有没有 delta 时，才把
        message.content 当作完整候选文本进行覆盖/补全，而不是盲目 append。
        """
        url = f"{self.BASE_URL}/v1/text/chatcompletion_v2"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "MiniMax-M2.5",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "group_id": self.group_id,
            "stream": True,
        }

        full_text = ""

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout,
                stream=True,
            )
        except requests.exceptions.Timeout:
            raise ValueError("AI 请求超时")
        except requests.exceptions.ConnectionError as e:
            raise ValueError(f"网络连接失败: {e}")

        if response.status_code != 200:
            preview = response.text[:500] if response.text else ""
            raise ValueError(f"API 请求失败: {response.status_code} {preview}")

        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue

            line = raw_line.strip()
            if not line.startswith("data:"):
                continue

            data = line[5:].strip()
            if data == "[DONE]":
                break

            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue

            choices = chunk.get("choices") or []
            if not choices:
                continue

            choice = choices[0] or {}
            delta = choice.get("delta") or {}
            message = choice.get("message") or {}

            delta_content = delta.get("content") or ""
            message_content = message.get("content") or ""

            if delta_content:
                full_text += delta_content
                if on_chunk:
                    on_chunk(full_text)
                continue

            if message_content:
                # message.content 通常是最终完整文本。不要追加到 delta 之后。
                if not full_text:
                    full_text = message_content
                    if on_chunk:
                        on_chunk(full_text)
                elif message_content.startswith(full_text) and len(message_content) > len(full_text):
                    full_text = message_content
                    if on_chunk:
                        on_chunk(full_text)
                # 如果 message_content 与已累计内容相同或更短，忽略，避免重复。

        return full_text

    def _parse_json_object(self, content: str) -> dict:
        """从包含额外文本的响应中尽量提取第一个 JSON 对象。"""
        cleaned = (content or "").strip()
        if not cleaned:
            raise ValueError("空响应，无法解析 JSON")

        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, re.IGNORECASE)
        if fenced:
            cleaned = fenced.group(1).strip()

        decoder = json.JSONDecoder()
        start = cleaned.find("{")
        while start != -1:
            try:
                obj, _end = decoder.raw_decode(cleaned[start:])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
            start = cleaned.find("{", start + 1)

        raise ValueError("未找到可解析的 JSON 对象")

    def _qa_fallback_json(self, message: str) -> str:
        """生成前端可稳定渲染的 Ask AI 兜底 JSON 字符串。"""
        payload = {
            "version": "qa_v1",
            "answer_type": "general",
            "grounding": {
                "source_used": False,
                "summary_used": False,
                "extension_used": False,
                "source_summary_conflict": False,
            },
            "sections": {
                "core_answer": [message or "抱歉，暂未能生成回答，请稍后重试。"],
                "source_explanation": [],
                "plain_language": [],
                "extra_context": [],
                "caution": [],
            },
            "followups": [],
            "disclaimer": "仅用于投资知识学习，不构成投资建议。",
        }
        return json.dumps(payload, ensure_ascii=False)

    def _ensure_string_list(self, value, max_items: int = 4) -> list[str]:
        """把模型返回的字段统一整理成字符串数组。"""
        if value is None:
            return []
        if isinstance(value, str):
            items = [value]
        elif isinstance(value, list):
            items = value
        else:
            items = [str(value)]

        result = []
        for item in items:
            text = str(item).strip()
            if text:
                result.append(text)
            if len(result) >= max_items:
                break
        return result

    def _normalize_qa_answer(self, content: str) -> dict:
        """把模型输出标准化成固定 qa_v1 schema。

        这里会从 fenced code、额外解释、重复 JSON 中提取第一个 JSON 对象，
        然后补齐缺失字段，保证前端可以稳定 JSON.parse。
        """
        parsed = self._parse_json_object(content)

        sections = parsed.get("sections") or {}
        if not isinstance(sections, dict):
            sections = {}

        grounding = parsed.get("grounding") or {}
        if not isinstance(grounding, dict):
            grounding = {}

        answer_type = str(parsed.get("answer_type") or "general").strip()
        valid_answer_types = {
            "concept",
            "operation_logic",
            "correctness_check",
            "stock_specific",
            "simple",
            "general",
        }
        if answer_type not in valid_answer_types:
            answer_type = "general"

        normalized = {
            "version": "qa_v1",
            "answer_type": answer_type,
            "grounding": {
                "source_used": bool(grounding.get("source_used", True)),
                "summary_used": bool(grounding.get("summary_used", True)),
                "extension_used": bool(grounding.get("extension_used", False)),
                "source_summary_conflict": bool(grounding.get("source_summary_conflict", False)),
            },
            "sections": {
                "core_answer": self._ensure_string_list(sections.get("core_answer"), 3),
                "source_explanation": self._ensure_string_list(sections.get("source_explanation"), 4),
                "plain_language": self._ensure_string_list(sections.get("plain_language"), 3),
                "extra_context": self._ensure_string_list(sections.get("extra_context"), 4),
                "caution": self._ensure_string_list(sections.get("caution"), 4),
            },
            "followups": self._ensure_string_list(parsed.get("followups"), 4),
            "disclaimer": "仅用于投资知识学习，不构成投资建议。",
        }

        if not normalized["sections"]["core_answer"]:
            normalized["sections"]["core_answer"] = ["原文没有提供足够信息直接回答这个问题。"]

        return normalized

    def polish(self, text: str, on_chunk: Optional[Callable[[str], None]] = None) -> str:
        """对文字进行润色"""
        if not text or not text.strip():
            return text

        system_prompt = """
你是一个专业的中文语音转写文本校对与润色助手，擅长处理股票知识分享、A股交易经验、盘面讲解、投资方法论、短线交易心得、复盘讲解等口语化内容。

你的任务是：在不改变原意、不新增观点、不添加投资建议的前提下，对语音转文字结果进行纠错、润色、断句、分段，使文本更准确、通顺、适合阅读。

核心原则：
1. 原意优先
   - 必须保留说话人的原始观点、判断逻辑、语气和表达倾向。
   - 不要替作者补充没有说过的观点。
   - 不要擅自扩展成投资建议、研报分析或结论判断。
   - 不要把口语内容过度书面化，保持自然的讲课/分享风格。

2. 最小必要修改
   - 只修正明显的转写错误、错别字、语序不顺、标点缺失和重复口癖。
   - 不确定的内容不要强行改写。
   - 对股票名称、股票代码、数字、价格、百分比、时间、涨跌幅、买入卖出方向等信息要特别谨慎，不能凭空猜测。

3. 纠正语音转写错误
   请根据上下文识别并修正因音质、口音、方言、连读、背景噪音导致的错误，包括但不限于：

   - 声母混淆：
     L/N 不分：拿/拉、哪/啦、内/雷、能/棱、弄/龙、农/隆等；
     ZH/Z、CH/C、SH/S 不分：知道/自到、市场/死场、趋势/区势、支撑/资撑等；
     H/F 不分：回踩/飞踩、换手/饭手、分歧/昏歧等；
     J/Q/X 混淆：情绪/形绪、启动/激动、前排/钱排等；
     D/T、B/P、G/K 等近音混淆：打板/塔板、补涨/普涨、格局/可局等。

   - 韵母混淆：
     an/ang、en/eng、in/ing、ou/uo、ai/ei 等导致的错字；
     例如：放量/放亮、承接/成接、行情/行琴、震荡/震当、回撤/回车等。

   - 连读和口语误识别：
     的/得/地、了/呢/着、在/再、这个/各个、一个/一哥、不是/布置、就是说/就说等；
     根据上下文选择最合理的字词。

4. 重点识别股票与交易领域术语
   对以下类型词汇要优先根据上下文纠正：

   - 股票基础术语：
     K线、均线、成交量、换手率、量价关系、筹码、盘口、分时、趋势、支撑位、压力位、缺口、箱体、突破、回踩、回撤、回抽、洗盘、出货。

   - A股短线交易术语：
     打板、低吸、半路、首板、二板、连板、涨停、跌停、炸板、回封、封单、扫板、排板、天地板、地天板、一字板、T字板、龙头、补涨、卡位、晋级、淘汰。

   - 市场情绪与题材术语：
     情绪周期、分歧、一致、弱转强、强更强、退潮、修复、主线、题材、板块轮动、资金抱团、赚钱效应、亏钱效应、承接、抛压、分歧转一致、一致转分歧。

   - 基本面与投资术语：
     估值、业绩、利润、营收、现金流、毛利率、净利率、PE、市盈率、PB、市净率、ROE、成长性、景气度、行业周期、护城河、分红、资产负债率。

   常见误识别示例：
   - 回彩、灰踩、归踩、会踩 → 回踩
   - 炸版、闸板 → 炸板
   - 首版 → 首板
   - 量价配和 → 量价配合
   - 筹马、筹吗 → 筹码
   - 成接、承结 → 承接
   - 换首、换守 → 换手
   - 分岐、分其 → 分歧
   - 情续、情絮 → 情绪
   - 主升浪被识别为“主生浪”“竹升浪”时，应根据上下文修正为“主升浪”
   - 龙头被识别为“龙投”“笼头”时，应根据上下文修正为“龙头”

   注意：以上只是示例，不要机械替换，必须结合上下文判断。

5. 添加合理标点
   - 根据语义添加逗号、句号、顿号、分号、冒号、问号、感叹号。
   - 问句加问号，强调语气可加感叹号，但不要滥用。
   - 对并列概念、交易条件、逻辑递进关系进行合理断句。
   - 不要让一句话过长。

6. 合理分段
   - 按照语义和话题变化分段。
   - 每段尽量聚焦一个意思。
   - 股票知识分享类文本可按照以下逻辑自然分段：
     市场背景 → 核心观点 → 判断依据 → 案例解释 → 操作思路 → 风险提醒 → 总结。
   - 但不要强行添加小标题，除非原文中本身有明显标题或层级。

7. 精简口癖和重复
   - 可以适度删除或压缩无意义口癖，例如：
     “然后然后”“就是就是”“这个这个”“那个那个”“啊”“嗯”“对吧”“你知道吧”等。
   - 但不要删除承载语气、转折、强调、条件判断的词。
   - 尤其不要误删“不”“不是”“不能”“不要”“但是”“除非”“如果”等关键逻辑词。

8. 保持口语化表达
   - 文本应像一位股票老师或交易者在自然讲解。
   - 可以让句子更通顺，但不要改成正式研报、新闻稿或学术文章。
   - 保留“我认为”“大家要注意”“这里要看”“这个位置不能追”等原有表达风格。

9. 严禁行为
   - 不要新增原文没有的股票、代码、数据、案例或结论。
   - 不要替作者判断某只股票能不能买。
   - 不要添加风险提示之外的新投资建议。
   - 不要输出解释、分析过程、修改说明。
   - 不要使用 Markdown 标题、项目符号或编号，除非原文中本身就有类似结构。
   - 不要在输出中写“以下是润色后的文本”。

输出要求：
直接输出润色、纠错、断句、分段后的纯文本。
不要添加任何解释、说明、标签、前后缀。
"""

        try:
            print(f"[Polisher] 润色请求，长度: {len(text)}")
            polished = self._stream_chat_completion(
                system_prompt=system_prompt,
                user_text=text,
                timeout=120,
                on_chunk=on_chunk,
            ).strip()
            print(f"[Polisher] 润色成功: {len(text)} -> {len(polished)}")
            return polished
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"润色失败: {str(e)}")

    def polish_long_text(self, text: str, max_chars: int = 2000) -> str:
        """长文本润色（自动分段）"""
        if not text:
            return text

        print(f"[Polisher] 长文本润色，总长度: {len(text)}")

        paragraphs = text.split("\n")
        results = []
        current = ""

        for para in paragraphs:
            if len(current) + len(para) > max_chars and current:
                polished = self.polish(current.strip())
                results.append(polished)
                current = para
            else:
                current = (current + "\n" + para) if current else para

        if current.strip():
            polished = self.polish(current.strip())
            results.append(polished)

        result = "\n".join(results)
        print(f"[Polisher] 润色完成: {len(result)} 字符")
        return result

    def summarize(self, text: str, on_chunk: Optional[Callable[[str], None]] = None) -> str:
        """AI 摘要与总结 - 返回适合流式展示的结构化纯文本"""
        if not text or not text.strip():
            return ""

        system_prompt = """你是一名专业的股票投资知识整理与学习助手，擅长从A股知识分享、交易经验、盘面讲解、选股方法、仓位管理、技术分析、基本面分析和投资心法类文本中，提炼可学习、可复盘、可迁移的方法论。

你的任务不是判断股票买卖，也不是给出投资建议，而是基于输入文本，提炼其中的知识点、交易逻辑、底层思路、适用场景和风险提醒。

请严格按以下纯文本结构输出，不要返回 JSON，不要返回 Markdown 代码块，不要添加任何解释：

核心主题：
用一句话概括这段分享主要讲什么，不超过50字

核心观点：
1. 观点1：提炼作者最重要的观点，不超过40字
2. 观点2
3. 观点3

关键知识点：
1. 知识点1：如选股逻辑、买入逻辑、卖出逻辑、仓位管理、风险控制、市场情绪、板块轮动、技术形态、基本面判断等，不超过40字
2. 知识点2
3. 知识点3

方法论框架：
看什么：作者主要关注的指标、信号、板块、情绪或基本面因素
怎么判断：作者判断机会或风险的核心依据
何时行动：满足什么条件才考虑行动
何时放弃：什么情况下应放弃或回避
如何控风险：作者提到或隐含的风险控制方式

可复用原则：
1. 如果……那么……
2. 当……时，需要……

适用场景：
1. 如短线交易、趋势行情、题材炒作、板块轮动、龙头股交易、震荡市等

失效场景：
1. 这套观点可能不适用或容易误判的情况

风险提醒：
1. 风险1：原文直接提到或根据原文逻辑推断出的风险，推断内容需注明“推断”
2. 风险2

新手误区：
1. 普通投资者容易误解或误用这段内容的地方

学习笔记：
一句话精华：这段内容最值得记住的一句话
三个关键词：关键词1、关键词2、关键词3
核心方法：最重要的可学习方法
最大风险：最需要警惕的风险
复盘问题：以后看类似股票或行情时值得反复追问的问题

可执行清单：
1. 是否符合作者提到的核心条件？
2. 是否存在明显风险？
3. 是否有明确买入或卖出依据？
4. 是否只是情绪冲动？
5. 是否做好仓位控制？

思考方式总结：
这段分享真正值得学习的思考方式，不超过50字

要求：
1. 严格基于原文内容整理，不要编造作者没有表达的观点。
2. 不要直接给出买入、卖出、持有等投资建议。
3. 不要把文本改写成研报，不要过度拔高。
4. 如果原文信息不足，对应字段可以写“原文未明确提及”。
5. 优先提炼方法论，而不是复述原文。
6. 过滤重复表述、语气词、寒暄、感谢语、无效口播内容。
7. 保留A股交易语境中的专业术语，如K线、打板、低吸、首板、连板、炸板、回封、换手、量价配合、筹码、承接、分歧、一致、情绪周期、板块轮动、龙头、补涨、卡位等。
8. 保持输出自然、清晰、适合逐段阅读。"""

        try:
            print(f"[Summarizer] 摘要请求，长度: {len(text)}")
            summary = self._stream_chat_completion(
                system_prompt=system_prompt,
                user_text=text,
                timeout=120,
                on_chunk=on_chunk,
            ).strip()
            print(f"[Summarizer] 摘要成功: {len(summary)} 字符")
            return summary
        except Exception as e:
            print(f"[Summarizer] 摘要失败: {e}")
            return ""

    def generate_post_metadata(self, polished_text: str, summary_text: str) -> dict:
        """生成 Markdown 导出所需的标题、分类和标签。"""
        if not polished_text.strip() and not summary_text.strip():
            return {
                "title": "未命名笔记",
                "categories": ["未分类"],
                "tags": ["待整理"],
            }

        system_prompt = """你是一名中文内容编辑助手，负责为一篇基于股票投资、交易复盘、知识分享的文章生成 Markdown front matter 元数据。

请根据用户提供的润色正文和摘要总结，提炼出：
1. title：一个简洁、自然、适合文章标题的中文标题，18字以内，不要带书名号
2. categories：1到2个分类，偏栏目级别，例如 交易复盘、投资方法、市场观察、仓位管理、龙头战法
3. tags：2到4个标签，偏关键词级别，例如 情绪周期、板块轮动、低吸、打板、风险控制

要求：
1. 输出必须是合法 JSON
2. 只输出 JSON，不要输出解释
3. categories 和 tags 都必须是字符串数组
4. 不要生成空数组
5. 如果信息不足，也要给出合理、通用但不过度夸张的结果

输出格式：
{
  "title": "文章标题",
  "categories": ["分类1", "分类2"],
  "tags": ["标签1", "标签2", "标签3"]
}"""

        user_text = f"""【润色正文】
{polished_text.strip()}

【摘要总结】
{summary_text.strip()}"""

        try:
            content = self._stream_chat_completion(
                system_prompt=system_prompt,
                user_text=user_text,
                timeout=60,
            ).strip()

            if not content:
                raise ValueError("元数据生成结果为空")

            parsed = self._parse_json_object(content)

            title = str(parsed.get("title") or "").strip() or "未命名笔记"
            categories = [str(item).strip() for item in (parsed.get("categories") or []) if str(item).strip()]
            tags = [str(item).strip() for item in (parsed.get("tags") or []) if str(item).strip()]

            return {
                "title": title,
                "categories": categories[:2] or ["未分类"],
                "tags": tags[:4] or ["待整理"],
            }
        except Exception as e:
            print(f"[Meta] 元数据生成失败: {e}")
            return {
                "title": "未命名笔记",
                "categories": ["未分类"],
                "tags": ["待整理"],
            }

    def polish_and_summarize(self, text: str) -> dict:
        """润色并摘要"""
        polished = self.polish(text)
        summary = self.summarize(polished)
        return {"polished": polished, "summary": summary}

    def ask_about_content(
        self,
        question: str,
        polished_text: str,
        summary_text: str,
    ) -> str:
        """根据润色文本和摘要内容，回答用户关于这段内容的问题。

        返回值永远是一个合法 JSON 字符串，schema 固定为 qa_v1。
        """
        system_prompt = """
你是一名专业的股票投资知识导师，擅长结合股票知识分享文本、AI摘要和用户问题，进行清晰、准确、可学习的问答讲解。

你的任务是：基于用户提供的「原文内容」和「AI摘要总结」回答用户问题，并在必要时结合通用股票知识进行扩展解释，帮助用户真正理解其中的投资逻辑、交易方法、术语含义和使用场景。

你必须严格遵守以下规则：

1. 回答优先级：
- 优先依据「原文内容」回答。
- 如果「AI摘要总结」与原文一致，可以参考摘要帮助组织答案。
- 如果原文和摘要存在冲突，以「原文内容」为准，并在 caution 中指出摘要可能存在简化或偏差。
- 如果用户问题在原文和摘要中没有明确答案，可以基于通用股票知识进行扩展补充，但必须设置 grounding.extension_used 为 true。
- 不允许把扩展补充说成是原文作者的观点。

2. 内容边界：
- 必须区分：原文明确提到的内容、根据原文逻辑合理推导的内容、原文未提到但可作为通用知识补充的内容。
- 不要编造原文没有的股票、案例、价格、数据、结论。
- 不要输出与问题无关的大段内容。
- 不要使用夸张、承诺收益、保证胜率等表达。
- 所有回答仅用于投资知识学习，不构成投资建议。

3. 问题类型处理：
- 如果用户问概念解释，例如 KDJ、金叉、死叉、背离、钝化、20日均线、板块轮动、情绪周期等：
  - core_answer 先用简单话解释概念。
  - source_explanation 说明原文中作者是怎么使用这个概念的。
  - caution 说明容易误解的地方。

- 如果用户问操作逻辑，例如“为什么不能直接买”“为什么要等确认”“什么时候进场”“什么时候卖出”等：
  - core_answer 先回答核心结论。
  - source_explanation 解释原文里的判断条件。
  - caution 说明风险和适用前提。
  - 不要直接给出具体买卖建议。

- 如果用户问某个说法对不对：
  - core_answer 先判断这个说法是否符合原文逻辑。
  - source_explanation 说明成立条件。
  - caution 说明失效场景或风险。

- 如果用户问具体股票、代码、价格、涨跌、能不能买、能不能卖：
  - 不要直接给出买入、卖出、持有建议。
  - 应转化为方法论回答。
  - 告诉用户应该依据哪些条件检查。
  - 可以给出观察清单，但不能替用户做投资决策。

4. 输出语言：
- 使用中文。
- 像老师讲课，语言通俗，逻辑清楚。
- 多解释“为什么”“怎么判断”“容易错在哪里”。
- 不要堆砌术语。
- 不要写成研报风格。

5. 输出格式：
你必须只输出一个合法 JSON 对象。
不要输出 Markdown。
不要输出代码块。
不要输出任何 JSON 之外的解释文字。
不要使用中文标题符号，例如【核心回答】。
不要在 JSON 前后添加说明。
所有字段必须存在。
如果某个部分不需要内容，使用空数组 []，不要省略字段。
每个数组元素必须是完整句子。
每个数组最多 4 条。
每条句子尽量控制在 80 个中文字符以内。
JSON内容不要重复输出

JSON 格式必须严格如下：
{
  "version": "qa_v1",
  "answer_type": "concept | operation_logic | correctness_check | stock_specific | simple | general",
  "grounding": {
    "source_used": true,
    "summary_used": true,
    "extension_used": false,
    "source_summary_conflict": false
  },
  "sections": {
    "core_answer": [],
    "source_explanation": [],
    "plain_language": [],
    "extra_context": [],
    "caution": []
  },
  "followups": [],
  "disclaimer": "仅用于投资知识学习，不构成投资建议。"
}
"""

        user_text = f"""【原文内容（润色后）】
{polished_text.strip()}

【AI 摘要总结】
{summary_text.strip()}

【用户问题】
{question.strip()}

请严格按照 system prompt 中的 JSON schema 输出。
只输出 JSON，不要输出 Markdown，不要输出解释文字。"""

        try:
            raw_answer = self._stream_chat_completion(
                system_prompt=system_prompt,
                user_text=user_text,
                timeout=60,
            ).strip()

            if not raw_answer:
                return self._qa_fallback_json("抱歉，暂未能生成回答，请稍后重试。")

            normalized = self._normalize_qa_answer(raw_answer)
            return json.dumps(normalized, ensure_ascii=False)
        except Exception as e:
            print(f"[Ask] 问答生成失败: {e}")
            return self._qa_fallback_json("抱歉，回答生成失败，请稍后重试。")
