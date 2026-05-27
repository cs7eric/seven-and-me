const BASE_URL = 'https://api.minimaxi.com';

const POLISH_SYSTEM_PROMPT = `你是一个专业的中文语音转写文本校对与润色助手，擅长处理股票知识分享、A股交易经验、盘面讲解、投资方法论、短线交易心得、复盘讲解等口语化内容。

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

   - 声母混淆：L/N、ZH/Z、CH/C、SH/S、H/F、J/Q/X、D/T、B/P、G/K 等近音混淆
   - 韵母混淆：an/ang、en/eng、in/ing、ou/uo、ai/ei 等
   - 连读和口语误识别：的/得/地、了/呢/着、在/再、这个/各个、一个/一哥、不是/布置、就是说/就说等

4. 重点识别股票与交易领域术语
   对K线、打板、低吸、首板、连板、炸板、回封、筹码、承接、分歧、一致、情绪周期、板块轮动、龙头、补涨、卡位等术语要优先根据上下文纠正。

5. 添加合理标点、合理分段、精简口癖

输出要求：直接输出润色、纠错、断句、分段后的纯文本，不要添加任何解释、说明。

输出：直接输出纯文本，不要加前后缀。`;

const SUMMARIZE_SYSTEM_PROMPT = `你是一名专业的股票投资知识整理与学习助手，擅长从A股知识分享、交易经验、盘面讲解、选股方法、仓位管理、技术分析、基本面分析和投资心法类文本中，提炼可学习、可复盘、可迁移的方法论。

你的任务不是判断股票买卖，也不是给出投资建议，而是基于输入文本，提炼其中的知识点、交易逻辑、底层思路、适用场景和风险提醒。

请严格按以下MARKDOWN格式输出，只返回纯MARKDOWN，不要有任何解释、说明、JSON或多余文字：

# 核心主题
用一句话概括这段分享主要讲什么，不超过50字

## 核心观点
- 观点1：提炼作者最重要的观点，不超过40字
- 观点2
- 观点3

## 关键知识点
- 知识点1：如选股逻辑、买入逻辑、卖出逻辑、仓位管理、风险控制、市场情绪、板块轮动、技术形态、基本面判断等，不超过40字
- 知识点2
- 知识点3

## 方法论框架
**看什么**：作者主要关注的指标、信号、板块、情绪或基本面因素

**怎么判断**：作者判断机会或风险的核心依据

**何时行动**：满足什么条件才考虑行动

**何时放弃**：什么情况下应放弃或回避

**如何控风险**：作者提到或隐含的风险控制方式

## 可复用原则
- 如果……那么……
- 当……时，需要……

## 适用场景
- 如短线交易、趋势行情、题材炒作、板块轮动、龙头股交易、震荡市等

## 失效场景
- 这套观点可能不适用或容易误判的情况

## 风险提醒
- 风险1：原文直接提到或根据原文逻辑推断出的风险，推断内容需注明"推断"

## 新手误区
- 普通投资者容易误解或误用这段内容的地方

## 学习笔记
**一句话精华**：这段内容最值得记住的一句话

**三个关键词**：关键词1、关键词2、关键词3

**核心方法**：最重要的可学习方法

**最大风险**：最需要警惕的风险

**复盘问题**：以后看类似股票或行情时值得反复追问的问题

## 可执行清单
- [ ] 是否符合作者提到的核心条件？
- [ ] 是否存在明显风险？
- [ ] 是否有明确买入或卖出依据？
- [ ] 是否只是情绪冲动？
- [ ] 是否做好仓位控制？

## 思考方式总结
这段分享真正值得学习的思考方式，不超过50字`;

interface MiniMaxStreamChunk {
  choices?: Array<{
    delta?: { content?: string };
    message?: { content?: string };
  }>;
}

export async function polish_stream(
  text: string,
  onChunk: (text: string) => void
): Promise<string> {
  if (!text || !text.trim()) return text;

  const apiKey = process.env.MINIMAX_API_KEY;
  const groupId = process.env.MINIMAX_GROUP_ID;
  if (!apiKey) throw new Error('请设置 MINIMAX_API_KEY');
  if (!groupId) throw new Error('请设置 MINIMAX_GROUP_ID');

  let fullText = '';
  const response = await fetch(`${BASE_URL}/v1/text/chatcompletion_v2`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: 'MiniMax-M2.5',
      messages: [
        { role: 'system', content: POLISH_SYSTEM_PROMPT },
        { role: 'user', content: text },
      ],
      group_id: groupId,
      stream: true,
    }),
  });

  if (!response.ok) {
    throw new Error(`API 请求失败: ${response.status}`);
  }

  if (!response.body) {
    throw new Error('响应没有 body');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  const newline = new Uint8Array([10]);

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value, { stream: true });
    const lines = chunk.split('\n');

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const data = line.slice(6).trim();
      if (data === '[DONE]') continue;

      try {
        const parsed: MiniMaxStreamChunk = JSON.parse(data);
        const content =
          parsed.choices?.[0]?.delta?.content ||
          parsed.choices?.[0]?.message?.content ||
          '';
        if (content) {
          fullText += content;
          onChunk(fullText);
        }
      } catch {}
    }
  }

  return fullText;
}

export async function summarize_stream(
  text: string,
  onChunk: (text: string) => void
): Promise<string> {
  if (!text || !text.trim()) return '';

  const apiKey = process.env.MINIMAX_API_KEY;
  const groupId = process.env.MINIMAX_GROUP_ID;
  if (!apiKey) throw new Error('请设置 MINIMAX_API_KEY');
  if (!groupId) throw new Error('请设置 MINIMAX_GROUP_ID');

  let fullText = '';
  const response = await fetch(`${BASE_URL}/v1/text/chatcompletion_v2`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: 'MiniMax-M2.5',
      messages: [
        { role: 'system', content: SUMMARIZE_SYSTEM_PROMPT },
        { role: 'user', content: text },
      ],
      group_id: groupId,
      stream: true,
    }),
  });

  if (!response.ok) {
    throw new Error(`API 请求失败: ${response.status}`);
  }

  if (!response.body) {
    throw new Error('响应没有 body');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value, { stream: true });
    const lines = chunk.split('\n');

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const data = line.slice(6).trim();
      if (data === '[DONE]') continue;

      try {
        const parsed: MiniMaxStreamChunk = JSON.parse(data);
        const content =
          parsed.choices?.[0]?.delta?.content ||
          parsed.choices?.[0]?.message?.content ||
          '';
        if (content) {
          fullText += content;
          onChunk(fullText);
        }
      } catch {}
    }
  }

  return fullText;
}