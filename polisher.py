import json
import os
import re
from pathlib import Path
from string import Template
from typing import Callable, Optional
from backend.services.ai_adapter_service import AIAdapterRouter


# 所有 prompt 维护在 prompt/ 目录下，文件名即用途
_PROMPT_DIR = Path(__file__).parent / "prompt"

# Ask AI（MP4 问答）
ASK_SYSTEM_PROMPT_FILE = _PROMPT_DIR / "ask_system.md"
ASK_USER_PROMPT_FILE = _PROMPT_DIR / "ask_user.md"

# 文本润色（polish）
POLISH_SYSTEM_PROMPT_FILE = _PROMPT_DIR / "polish_system.md"

# 摘要（summarize）
SUMMARIZE_SYSTEM_PROMPT_FILE = _PROMPT_DIR / "summarize_system.md"

# Markdown front matter 元数据
METADATA_SYSTEM_PROMPT_FILE = _PROMPT_DIR / "metadata_system.md"
METADATA_USER_PROMPT_FILE = _PROMPT_DIR / "metadata_user.md"


def _load_prompt(path: Path) -> str:
    """从 prompt/ 目录加载 prompt 文本，文件不存在时抛出带路径的明确错误。"""
    if not path.exists():
        raise FileNotFoundError(
            f"[Prompt] Prompt 文件缺失: {path}，请到 prompt/ 目录下维护对应 .md 文件"
        )
    return path.read_text(encoding="utf-8").strip()


class TextPolisher:
    """AI 润色模块 - 基于 MiniMax API"""

    BASE_URL = "https://api.minimaxi.com"

    def __init__(self, api_key: Optional[str] = None, group_id: Optional[str] = None):
        self.api_key = api_key or os.getenv("MINIMAX_API_KEY")
        self.group_id = group_id or os.getenv("MINIMAX_GROUP_ID")
        self.ai_router = AIAdapterRouter()

        if self.api_key:
            print(f"[Polisher] API Key: {self.api_key[:12]}...")
        else:
            print("[Polisher] API Key: <configured by AI Provider registry>")

    def _stream_chat_completion(
        self,
        system_prompt: str,
        user_text: str,
        timeout: int = 120,
        on_chunk: Optional[Callable[[str], None]] = None,
        capability: str = "text_polish",
        fallback_model: str = "MiniMax-M2.5",
    ) -> str:
        """调用 MiniMax 流式接口，并在每次有增量时回调当前完整文本。

        MiniMax 的流式返回有时会在 delta 增量之后，再给一次完整 message.content。
        如果把 delta.content 和 message.content 都直接拼接，就会得到：
        `{...json...}{...json...}` 或 ```json...``````json...```。
        这里的规则是：优先使用 delta 增量；只有没有 delta 时，才把
        message.content 当作完整候选文本进行覆盖/补全，而不是盲目 append。
        """
        response = self.ai_router.chat_completion(
            capability=capability,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            fallback_model=fallback_model,
            fallback_base_url=self.BASE_URL,
            fallback_timeout=timeout,
            stream=True,
            on_chunk=on_chunk,
        )
        return response.content

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

        system_prompt = _load_prompt(POLISH_SYSTEM_PROMPT_FILE)

        try:
            print(f"[Polisher] 润色请求，长度: {len(text)}")
            polished = self._stream_chat_completion(
                system_prompt=system_prompt,
                user_text=text,
                timeout=120,
                on_chunk=on_chunk,
                capability="text_polish",
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

        system_prompt = _load_prompt(SUMMARIZE_SYSTEM_PROMPT_FILE)

        try:
            print(f"[Summarizer] 摘要请求，长度: {len(text)}")
            summary = self._stream_chat_completion(
                system_prompt=system_prompt,
                user_text=text,
                timeout=120,
                on_chunk=on_chunk,
                capability="text_summary",
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

        system_prompt = _load_prompt(METADATA_SYSTEM_PROMPT_FILE)

        user_text = Template(_load_prompt(METADATA_USER_PROMPT_FILE)).substitute(
            polished_text=polished_text.strip(),
            summary_text=summary_text.strip(),
        )

        try:
            content = self._stream_chat_completion(
                system_prompt=system_prompt,
                user_text=user_text,
                timeout=60,
                capability="post_metadata",
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
        system_prompt = _load_prompt(ASK_SYSTEM_PROMPT_FILE)

        user_text = Template(_load_prompt(ASK_USER_PROMPT_FILE)).substitute(
            polished_text=polished_text.strip(),
            summary_text=summary_text.strip(),
            question=question.strip(),
        )

        try:
            raw_answer = self._stream_chat_completion(
                system_prompt=system_prompt,
                user_text=user_text,
                timeout=60,
                capability="mp4_qa",
            ).strip()

            if not raw_answer:
                return self._qa_fallback_json("抱歉，暂未能生成回答，请稍后重试。")

            normalized = self._normalize_qa_answer(raw_answer)
            return json.dumps(normalized, ensure_ascii=False)
        except Exception as e:
            print(f"[Ask] 问答生成失败: {e}")
            return self._qa_fallback_json("抱歉，回答生成失败，请稍后重试。")
