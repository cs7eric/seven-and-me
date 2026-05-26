import os
import requests
from typing import Optional


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

    def polish(self, text: str) -> str:
        """对文字进行润色"""
        if not text or not text.strip():
            return text

        system_prompt = """你是一个专业的中文文本润色师。

请对输入的语音转写文本进行润色，直接输出润色后的文本，不要添加任何说明。"""

        try:
            url = f"{self.BASE_URL}/v1/text/chatcompletion_v2"

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": "MiniMax-M2.5",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ],
                "group_id": self.group_id
            }

            print(f"[Polisher] 发送请求，长度: {len(text)}")

            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=120
            )

            print(f"[Polisher] 状态: {response.status_code}")
            print(f"[Polisher] 响应: {response.text[:500]}")

            if response.status_code != 200:
                raise ValueError(f"API 请求失败: {response.status_code}")

            result = response.json()

            if "choices" in result and len(result["choices"]) > 0:
                polished = result["choices"][0]["message"]["content"].strip()
                print(f"[Polisher] 润色成功: {len(text)} -> {len(polished)}")
                return polished
            else:
                raise ValueError(f"API 返回格式异常: {result}")

        except requests.exceptions.Timeout:
            raise ValueError("润色请求超时")
        except requests.exceptions.ConnectionError as e:
            raise ValueError(f"网络连接失败: {e}")
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

    def summarize(self, text: str) -> dict:
        """AI 摘要与总结 - 返回固定结构"""
        if not text or not text.strip():
            return {"核心内容": "", "关键要点": [], "待办事项": []}

        system_prompt = """你是一位专业的A股投资顾问，专注于股票交易、板块轮动、打板策略等技术分析。你需要对输入的文本进行专业摘要。

输出严格按以下JSON格式，只返回纯JSON，不要有其他文字：
{"核心内容": "一段话概括本次分享的核心投资逻辑或策略（不超过50字）", "关键要点": ["要点1（专业术语：K线/板块/打板/量价配合等，不超过30字）", "要点2", "要点3"]}

要求：
- 关键要点不超过5条，每条使用专业术语
- 过滤掉重复表述、语气词、感谢语等无效内容
- 提炼出可执行的交易逻辑（如：突破确认、首板效应、板块联动等）"""

        try:
            url = f"{self.BASE_URL}/v1/text/chatcompletion_v2"

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": "MiniMax-M2.5",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ],
                "group_id": self.group_id
            }

            response = requests.post(url, headers=headers, json=payload, timeout=60)

            if response.status_code != 200:
                raise ValueError(f"API 请求失败: {response.status_code}")

            result = response.json()
            content = result["choices"][0]["message"]["content"].strip()

            import json
            try:
                summary = json.loads(content)
                return {
                    "核心内容": summary.get("核心内容", ""),
                    "关键要点": summary.get("关键要点", []),
                }
            except json.JSONDecodeError:
                return {"核心内容": content[:100], "关键要点": [], "待办事项": []}

        except Exception as e:
            print(f"[Summarizer] 摘要失败: {e}")
            return {"核心内容": "", "关键要点": [], "待办事项": []}