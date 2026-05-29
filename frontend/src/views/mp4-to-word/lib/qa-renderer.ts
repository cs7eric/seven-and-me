import { escapeHtml, escapeHtmlAttr } from "./html";

const QA_ANSWER_TYPE_LABELS: Record<string, string> = {
  concept: "Concept",
  operation_logic: "Trading Logic",
  correctness_check: "Analysis",
  stock_specific: "Stock Specific",
  simple: "Simple Q",
  general: "General",
};

function toQaArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item ?? "").trim()).filter(Boolean);
  }
  if (value === null || value === undefined) return [];
  return String(value)
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line.replace(/^[-.*]\s*/, "").replace(/^\d+[.,)]\s*/, "").trim())
    .filter(Boolean);
}

function parseQaJsonAnswer(answer: string | object): Record<string, unknown> | null {
  if (answer && typeof answer === "object") {
    if ((answer as Record<string, unknown>).answer !== undefined) {
      return parseQaJsonAnswer((answer as Record<string, unknown>).answer as string | object);
    }
    return answer as Record<string, unknown>;
  }

  let raw = String(answer ?? "").trim();
  const fenced = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fenced?.[1]) raw = fenced[1].trim();
  if (!raw) return null;

  const start = raw.indexOf("{");
  if (start === -1) return null;

  let depth = 0;
  let inString = false;
  let escaped = false;
  let end = -1;

  for (let i = start; i < raw.length; i++) {
    const ch = raw[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') {
      inString = true;
      continue;
    }
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) {
        end = i + 1;
        break;
      }
    }
  }

  if (end > start) {
    try {
      return JSON.parse(raw.slice(start, end));
    } catch {
      return null;
    }
  }

  return null;
}

function normalizeQaJsonAnswer(answer: string | object) {
  const parsed = parseQaJsonAnswer(answer);
  if (!parsed || typeof parsed !== "object") return null;

  const sections =
    (parsed.sections && typeof parsed.sections === "object"
      ? parsed.sections
      : {}) as Record<string, unknown>;
  const grounding =
    (parsed.grounding && typeof parsed.grounding === "object"
      ? parsed.grounding
      : {}) as Record<string, unknown>;

  return {
    version: String(parsed.version || "qa_v1"),
    answer_type: String(parsed.answer_type || "general"),
    grounding: {
      source_used: Boolean(grounding.source_used),
      summary_used: Boolean(grounding.summary_used),
      extension_used: Boolean(grounding.extension_used),
      source_summary_conflict: Boolean(grounding.source_summary_conflict),
    },
    sections: {
      core_answer: toQaArray(sections.core_answer),
      source_explanation: toQaArray(sections.source_explanation),
      plain_language: toQaArray(sections.plain_language),
      extra_context: toQaArray(sections.extra_context),
      caution: toQaArray(sections.caution),
    },
    followups: toQaArray(parsed.followups).slice(0, 4),
    disclaimer: String(parsed.disclaimer || "仅用于投资知识学习，不构成投资建议。").trim(),
  };
}

function parseQaSections(text: string): Array<{ title: string; content: string }> {
  const source = String(text || "").replace(/\r\n/g, "\n");
  const lines = source.split("\n");
  const sections: Array<{ title: string; content: string }> = [];
  let current: { title: string; lines: string[] } | null = null;

  function pushCurrent() {
    if (!current) return;
    const content = current.lines.join("\n").trim();
    if (current.title || content) {
      sections.push({ title: current.title, content });
    }
  }

  for (const line of lines) {
    const trimmed = line.trim();
    const match = trimmed.match(/^#{0,6}\s*【([^】]+)】\s*[：:]?\s*(.*)$/);

    if (match) {
      pushCurrent();
      current = {
        title: String(match[1] || "").trim(),
        lines: match[2] ? [match[2]] : [],
      };
      continue;
    }

    if (!current) current = { title: "", lines: [] };
    current.lines.push(line);
  }

  pushCurrent();
  return sections.filter((section) => section.title || section.content);
}

function renderQaJsonLines(lines: string[], options: { risk?: boolean; compact?: boolean } = {}): string {
  const items = toQaArray(lines);
  if (!items.length) return "";

  const { risk = false, compact = false } = options;
  const dot = risk ? "!" : "•";

  return `<div class="${compact ? "qa-json-lines compact" : "qa-json-lines"}">${items
    .map(
      (line, index) =>
        `<div class="qa-json-line ${risk ? "risk" : ""}"><span class="qa-json-line-dot">${compact ? index + 1 : dot}</span><span>${escapeHtml(line)}</span></div>`
    )
    .join("")}</div>`;
}

function renderQaStatusPills(model: {
  answer_type: string;
  grounding: Record<string, boolean>;
}): string {
  const typeLabel = QA_ANSWER_TYPE_LABELS[model.answer_type] || model.answer_type || "General";
  const pills = [`<span class="qa-json-pill primary">${escapeHtml(typeLabel)}</span>`];

  if (model.grounding.source_used) pills.push('<span class="qa-json-pill">From Transcript</span>');
  if (model.grounding.summary_used) pills.push('<span class="qa-json-pill">From Summary</span>');
  if (model.grounding.extension_used) pills.push('<span class="qa-json-pill accent">Extended</span>');
  if (model.grounding.source_summary_conflict) pills.push('<span class="qa-json-pill warn">Conflict</span>');

  return pills.join("");
}

function renderQaLogicSection(model: { sections: Record<string, string[]> }): string {
  const source = model.sections.source_explanation || [];
  const plain = model.sections.plain_language || [];
  if (!source.length && !plain.length) return "";

  return `<section class="qa-json-logic">${
    source.length
      ? `<div class="qa-json-logic-pane source"><div class="qa-json-pane-head"><span class="qa-json-pane-icon">↳</span><div><div class="qa-json-pane-title">Based on Transcript</div><div class="qa-json-pane-subtitle">Explains the source content</div></div></div>${renderQaJsonLines(source)}</div>`
      : ""
  }${source.length && plain.length ? '<div class="qa-json-flow-arrow">→</div>' : ""}${
    plain.length
      ? `<div class="qa-json-logic-pane simple"><div class="qa-json-pane-head"><span class="qa-json-pane-icon">✦</span><div><div class="qa-json-pane-title">Plain Explanation</div><div class="qa-json-pane-subtitle">Explains the logic in simple terms</div></div></div>${renderQaJsonLines(plain)}</div>`
      : ""
  }</section>`;
}

function renderQaSupportSection(model: { sections: Record<string, string[]> }): string {
  const extra = model.sections.extra_context || [];
  const caution = model.sections.caution || [];
  if (!extra.length && !caution.length) return "";

  return `<section class="qa-json-support ${extra.length && caution.length ? "two" : "one"}">${
    extra.length
      ? `<div class="qa-json-support-block extra"><div class="qa-json-support-title"><span>＋</span><span>扩展补充</span></div>${renderQaJsonLines(extra)}</div>`
      : ""
  }${
    caution.length
      ? `<div class="qa-json-support-block risk"><div class="qa-json-support-title"><span>!</span><span>注意事项</span></div>${renderQaJsonLines(caution, { risk: true })}</div>`
      : ""
  }</section>`;
}

function renderQaFollowups(followups: string[]): string {
  if (!followups.length) return "";
  return `<div class="qa-json-followups"><span class="qa-json-followup-label">继续追问</span>${followups
    .map((item) => `<button class="qa-followup-chip" data-followup="${escapeHtmlAttr(item)}">${escapeHtml(item)}</button>`)
    .join("")}</div>`;
}

function qaJsonPlainText(
  model: {
    answer_type: string;
    sections: Record<string, string[]>;
    followups: string[];
    disclaimer: string;
  },
  question = ""
): string {
  const labels: Record<string, string> = {
    core_answer: "核心回答",
    source_explanation: "结合原文解释",
    plain_language: "通俗理解",
    extra_context: "扩展补充",
    caution: "注意事项",
  };

  const blocks = [
    question ? `问题：${question}` : "",
    `回答类型：${QA_ANSWER_TYPE_LABELS[model.answer_type] || model.answer_type || "General"}`,
    ...["core_answer", "source_explanation", "plain_language", "extra_context", "caution"].flatMap((key) => {
      const lines = model.sections[key] || [];
      if (!lines.length) return [];
      return [`\n【${labels[key]}】`, ...lines.map((line, index) => `${index + 1}. ${line}`)];
    }),
    ...(model.followups.length ? ["\n【继续追问】", ...model.followups.map((line, index) => `${index + 1}. ${line}`)] : []),
    model.disclaimer ? `\n${model.disclaimer}` : "",
  ];

  return blocks.filter(Boolean).join("\n");
}

function renderQaJsonAnswer(
  model: {
    answer_type: string;
    grounding: Record<string, boolean>;
    sections: Record<string, string[]>;
    followups: string[];
    disclaimer: string;
  },
  question = ""
): string {
  const core = model.sections.core_answer || [];
  const source = model.sections.source_explanation || [];
  const plain = model.sections.plain_language || [];
  const fallbackCore = core.length
    ? core
    : source.length
      ? source.slice(0, 2)
      : plain.length
        ? plain.slice(0, 2)
        : ["这个问题需要结合原文内容进一步判断。"];

  const fullText = qaJsonPlainText(model, question);
  const safeFullText = escapeHtmlAttr(fullText);
  const safeTitle = escapeHtmlAttr(question ? `Ask AI Answer · ${question}` : "Ask AI Answer");

  return `<div class="qa-json-response"><div class="qa-json-top"><div><div class="qa-json-eyebrow">AI Structured Answer</div><div class="qa-json-title">答案逻辑板</div></div><div class="qa-json-pills">${renderQaStatusPills(model)}</div></div><section class="qa-json-core"><div class="qa-json-core-label"><span class="qa-json-core-mark">✦</span><span>核心回答</span></div>${renderQaJsonLines(fallbackCore, { compact: true })}</section>${renderQaLogicSection(model)}${renderQaSupportSection(model)}<div class="qa-json-footer"><div class="qa-json-actions"><button class="qa-action-btn copy-full-qa" data-copy="${safeFullText}">Copy</button><button class="qa-action-btn read-full-qa" data-text="${safeFullText}" data-title="${safeTitle}">Expand</button></div>${model.disclaimer ? `<div class="qa-json-disclaimer">${escapeHtml(model.disclaimer)}</div>` : ""}</div>${renderQaFollowups(model.followups)}</div>`;
}

function renderLegacyQaAnswer(answer: string, question = ""): string {
  const raw = String(answer || "").trim();
  const sections = parseQaSections(raw);
  const map = new Map<string, string>();

  for (const section of sections) {
    const title = String(section.title || "").replace(/[【】]/g, "").replace(/[：:]$/, "").trim();
    const content = String(section.content || "").trim();
    if (title && content) map.set(title, content);
  }

  const legacyModel = {
    answer_type: "general",
    grounding: {
      source_used: Boolean(map.get("结合原文解释")),
      summary_used: false,
      extension_used: Boolean(map.get("扩展补充")),
      source_summary_conflict: false,
    },
    sections: {
      core_answer: toQaArray(map.get("核心回答") || raw),
      source_explanation: toQaArray(map.get("结合原文解释")),
      plain_language: toQaArray(map.get("通俗理解")),
      extra_context: toQaArray(map.get("扩展补充")),
      caution: toQaArray(map.get("注意事项")),
    },
    followups: [],
    disclaimer: "仅用于投资知识学习，不构成投资建议。",
  };

  return renderQaJsonAnswer(legacyModel, question);
}

export function renderQaAnswer(answer: string, question = ""): string {
  const raw = (answer || "").trim();
  if (!raw) return '<div class="qa-fallback-card">暂无回答内容</div>';

  const model = normalizeQaJsonAnswer(raw);
  if (model && model.version === "qa_v1") {
    return renderQaJsonAnswer(model, question);
  }

  return renderLegacyQaAnswer(String(raw || ""), question);
}
