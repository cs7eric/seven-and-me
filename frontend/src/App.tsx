import { useRef, useState, useCallback, useEffect } from "react";
import type { Phase, SSEEvent } from "./lib/types";
import {
  uploadFile,
  createSSEConnection,
  askQuestion,
  exportMarkdown,
} from "./lib/api";
import {
  parseSummarySections,
  getSectionMap,
  getLines,
  getContent,
  firstMeaningfulLine,
} from "./lib/summary-utils";

const STEPS = ["Upload", "Convert", "Transcribe", "Polish", "Summary"];
const SUMMARY_ORDER = [
  "核心主题",
  "核心观点",
  "关键知识点",
  "方法论框架",
  "可复用原则",
  "适用场景",
  "可执行清单",
  "风险提醒",
  "失效场景",
  "新手误区",
  "学习笔记",
  "思考方式总结",
  "摘要内容",
] as const;

const QA_STYLE_FIX = `
.qa-section {
  margin-top: 14px;
  border-top: 1px solid rgba(15, 23, 42, 0.07);
  padding-top: 14px;
}
.qa-box {
  background: rgba(255, 255, 255, 0.76);
  border: 1px solid rgba(255, 255, 255, 0.92);
  border-radius: 28px;
  overflow: hidden;
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.1);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
}
.qa-body {
  padding: 18px 18px 20px;
  background:
    radial-gradient(circle at 8% 0%, rgba(0, 113, 227, 0.05), transparent 28%),
    rgba(255, 255, 255, 0.2);
}
.qa-input-wrap {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  margin-bottom: 14px;
}
.qa-input {
  flex: 1;
  padding: 8px 14px;
  border: 1.5px solid rgba(15, 23, 42, 0.12);
  border-radius: 14px;
  font-size: 13px;
  font-family: inherit;
  color: #1d1d1f;
  background: rgba(255, 255, 255, 0.7);
  outline: none;
  transition: border-color 0.2s ease;
  resize: none;
  min-height: 38px;
  max-height: 100px;
}
.qa-input:focus {
  border-color: #0071e3;
  background: #fff;
}
.qa-input::placeholder { color: #86868b; }
.qa-submit {
  background: linear-gradient(180deg, #0a84ff 0%, #0071e3 100%);
  color: #fff;
  border: none;
  padding: 8px 16px;
  border-radius: 14px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(0, 113, 227, 0.2);
  transition: all 0.2s ease;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 5px;
  align-self: flex-end;
}
.qa-submit:hover:not(:disabled) { transform: translateY(-1px); }
.qa-submit:disabled { opacity: 0.5; cursor: not-allowed; box-shadow: none; }
.qa-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.qa-empty {
  border-radius: 18px;
  padding: 16px;
  color: #86868b;
  font-size: 13px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px dashed rgba(15, 23, 42, 0.08);
}
.qa-item {
  background: rgba(255, 255, 255, 0.74) !important;
  border: 1px solid rgba(255, 255, 255, 0.96) !important;
  border-radius: 26px !important;
  overflow: hidden !important;
  margin-bottom: 0 !important;
  box-shadow: 0 18px 52px rgba(15, 23, 42, 0.08) !important;
  backdrop-filter: blur(18px) !important;
  -webkit-backdrop-filter: blur(18px) !important;
}
.qa-item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px !important;
  cursor: pointer;
  gap: 12px;
  user-select: none;
  background: rgba(255, 255, 255, 0.68) !important;
  border-bottom: 1px solid rgba(15, 23, 42, 0.06) !important;
}
.qa-item-header:hover {
  background: linear-gradient(180deg, rgba(247, 249, 252, 0.98) 0%, rgba(240, 243, 248, 0.95) 100%);
}
.qa-item-q-text {
  font-size: 13px !important;
  line-height: 1.45 !important;
  color: #1f2937 !important;
  font-weight: 680 !important;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 8px;
}
.qa-item-q-text.expanded { white-space: normal; }
.qa-item-q-text::before {
  content: 'Q' !important;
  width: 22px !important;
  height: 22px !important;
  border-radius: 10px !important;
  font-size: 10px !important;
  background: linear-gradient(135deg, #0a84ff, #0071e3) !important;
  color: #fff !important;
  box-shadow: 0 8px 16px rgba(0, 113, 227, 0.22) !important;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-weight: 700;
}
.qa-item-toggle {
  color: #86868b;
  transition: transform 0.25s ease;
  flex-shrink: 0;
}
.qa-item-toggle.open { transform: rotate(180deg); }
.qa-item-body {
  display: none;
  border-top: 1px solid rgba(15, 23, 42, 0.06);
  background: rgba(255, 255, 255, 0.5);
}
.qa-item-body.open { display: block; }
.qa-answer-body {
  max-height: 760px !important;
  padding: 10px 12px 12px !important;
  overflow-y: auto !important;
  background:
    radial-gradient(circle at 0% 0%, rgba(0, 113, 227, 0.04), transparent 28%),
    rgba(255, 255, 255, 0.24) !important;
}
.qa-answer-body::-webkit-scrollbar { width: 6px; }
.qa-answer-body::-webkit-scrollbar-track { background: transparent; }
.qa-answer-body::-webkit-scrollbar-thumb { background: rgba(110, 110, 115, 0.28); border-radius: 999px; }
.qa-answer {
  background: linear-gradient(135deg, rgba(0, 113, 227, 0.04), rgba(10, 132, 255, 0.06));
  border: 1px solid rgba(0, 113, 227, 0.12);
  border-radius: 16px;
  padding: 14px 16px;
  font-size: 13.5px;
  line-height: 1.85;
  color: #1d1d1f;
  white-space: pre-wrap;
  word-break: break-word;
}
.qa-item-body .qa-answer {
  margin: 0;
  border: none;
  background: none;
  padding: 0;
  font-size: 14px;
  line-height: 1.9;
  color: #1d1d1f;
  white-space: normal;
}
.qa-json-response {
  display: block;
  padding: 14px;
  background:
    radial-gradient(circle at 0% 0%, rgba(0, 113, 227, 0.08), transparent 35%),
    radial-gradient(circle at 100% 10%, rgba(52, 199, 89, 0.06), transparent 34%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.86), rgba(248, 250, 252, 0.84));
  border-radius: 18px;
  white-space: normal;
}
.qa-json-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.qa-json-eyebrow {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #0071e3;
}
.qa-json-title {
  margin-top: 4px;
  font-size: 20px;
  font-weight: 760;
  color: #111827;
  letter-spacing: -0.02em;
}
.qa-json-pills {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.qa-json-pill {
  display: inline-flex;
  align-items: center;
  padding: 5px 10px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.055);
  color: #6b7280;
  font-size: 11px;
  font-weight: 760;
}
.qa-json-pill.primary {
  background: rgba(0, 113, 227, 0.1);
  color: #0071e3;
}
.qa-json-pill.accent {
  background: rgba(52, 199, 89, 0.12);
  color: #0f9f47;
}
.qa-json-pill.warn {
  background: rgba(245, 158, 11, 0.14);
  color: #b45309;
}
.qa-json-core {
  position: relative;
  overflow: hidden;
  border-radius: 24px;
  padding: 18px;
  color: #fff;
  background:
    radial-gradient(circle at 96% 0%, rgba(255, 255, 255, 0.24), transparent 34%),
    linear-gradient(135deg, #0a84ff 0%, #0071e3 54%, #155bd5 100%);
  box-shadow: 0 18px 42px rgba(0, 113, 227, 0.22);
  margin-bottom: 14px;
}
.qa-json-core::after {
  content: "";
  position: absolute;
  right: -54px;
  bottom: -68px;
  width: 172px;
  height: 172px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.12);
  pointer-events: none;
}
.qa-json-core-label {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.16);
  border: 1px solid rgba(255, 255, 255, 0.18);
  font-size: 12px;
  font-weight: 760;
  color: rgba(255, 255, 255, 0.96);
  margin-bottom: 12px;
}
.qa-json-core-mark {
  width: 20px;
  height: 20px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.18);
  color: #fff;
  font-size: 11px;
}
.qa-json-core .qa-json-lines.compact {
  gap: 12px;
}
.qa-json-core .qa-json-line {
  color: rgba(255, 255, 255, 0.98);
  font-size: 15px;
  line-height: 1.88;
  font-weight: 680;
  letter-spacing: -0.01em;
}
.qa-json-core .qa-json-line-dot {
  width: 26px;
  height: 26px;
  background: rgba(255, 255, 255, 0.16);
  color: #fff;
  font-size: 11px;
  font-weight: 800;
}
.qa-json-lines {
  display: grid;
  gap: 8px;
}
.qa-json-lines.compact { gap: 10px; }
.qa-json-line {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 10px;
  align-items: flex-start;
  color: #374151;
  font-size: 13px;
  line-height: 1.72;
}
.qa-json-line-dot {
  width: 24px;
  height: 24px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 113, 227, 0.1);
  color: #0071e3;
  font-size: 11px;
  font-weight: 800;
}
.qa-json-line.risk .qa-json-line-dot {
  background: rgba(245, 158, 11, 0.14);
  color: #b45309;
}
.qa-json-logic {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 12px;
  align-items: stretch;
  margin-bottom: 14px;
}
.qa-json-logic-pane {
  border-radius: 20px;
  padding: 16px;
  background: rgba(255, 255, 255, 0.76);
  border: 1px solid rgba(15, 23, 42, 0.06);
}
.qa-json-pane-head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 12px;
}
.qa-json-pane-icon {
  width: 26px;
  height: 26px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 113, 227, 0.1);
  color: #0071e3;
  font-weight: 800;
  flex-shrink: 0;
}
.qa-json-pane-title {
  font-size: 12px;
  font-weight: 780;
  color: #111827;
}
.qa-json-pane-subtitle {
  margin-top: 2px;
  font-size: 11px;
  line-height: 1.5;
  color: #6e6e73;
}
.qa-json-flow-arrow {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #0071e3;
  font-size: 18px;
  font-weight: 800;
}
.qa-json-support {
  display: grid;
  gap: 12px;
  margin-bottom: 14px;
}
.qa-json-support.two { grid-template-columns: 1fr 1fr; }
.qa-json-support.one { grid-template-columns: 1fr; }
.qa-json-support-block {
  border-radius: 20px;
  padding: 16px;
  background: rgba(255, 255, 255, 0.76);
  border: 1px solid rgba(15, 23, 42, 0.06);
}
.qa-json-support-block.risk {
  background: linear-gradient(180deg, rgba(255, 247, 237, 0.98), rgba(255, 255, 255, 0.86));
  border-color: rgba(245, 158, 11, 0.18);
}
.qa-json-support-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 780;
  color: #111827;
  margin-bottom: 10px;
}
.qa-json-footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.qa-json-actions,
.qa-json-followups {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.qa-json-followups { margin-top: 14px; }
.qa-json-followup-label {
  font-size: 12px;
  font-weight: 760;
  color: #6e6e73;
}
.qa-action-btn,
.qa-followup-chip {
  border: 1px solid rgba(0, 113, 227, 0.12) !important;
  background: rgba(0, 113, 227, 0.075) !important;
  color: #0071e3 !important;
  border-radius: 999px !important;
  padding: 7px 11px !important;
  font-size: 12px !important;
  font-weight: 740 !important;
  cursor: pointer !important;
  display: inline-flex !important;
  align-items: center !important;
  gap: 6px !important;
  transition: all 0.18s ease !important;
  width: auto !important;
  height: auto !important;
}
.qa-action-btn:hover,
.qa-followup-chip:hover {
  transform: translateY(-1px);
  background: rgba(0, 113, 227, 0.12) !important;
}
.qa-json-disclaimer {
  font-size: 11px;
  line-height: 1.6;
  color: #6e6e73;
}
.qa-fallback-card {
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid rgba(15, 23, 42, 0.06);
  padding: 16px;
  font-size: 14px;
  line-height: 1.86;
  color: #1f2937;
}
@media (max-width: 900px) {
  .qa-input-wrap {
    flex-direction: column;
    align-items: stretch;
  }
  .qa-submit {
    align-self: stretch;
    justify-content: center;
  }
  .qa-json-top,
  .qa-json-footer {
    flex-direction: column;
  }
  .qa-json-logic,
  .qa-json-support.two {
    grid-template-columns: 1fr;
  }
  .qa-json-flow-arrow {
    display: none;
  }
}
`;

function escapeHtml(value: string): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeHtmlAttr(value: string): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
    .replace(/\n/g, "&#10;")
    .replace(/\r/g, "&#13;");
}

function toQaArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((item) => String(item ?? "").trim())
      .filter(Boolean);
  }
  if (value === null || value === undefined) return [];
  return String(value)
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) =>
      line
        .replace(/^[-.*]\s*/, "")
        .replace(/^\d+[.,)]\s*/, "")
        .trim()
    )
    .filter(Boolean);
}

function parseQaJsonAnswer(answer: string | object): Record<string, unknown> | null {
  if (answer && typeof answer === "object") {
    if ((answer as Record<string, unknown>).answer !== undefined) {
      return parseQaJsonAnswer(
        (answer as Record<string, unknown>).answer as string | object
      );
    }
    return answer as Record<string, unknown>;
  }

  let raw = String(answer ?? "").trim();
  const fenced = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fenced && fenced[1]) raw = fenced[1].trim();
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
      if (escaped) {
        escaped = false;
      } else if (ch === "\\") {
        escaped = true;
      } else if (ch === '"') {
        inString = false;
      }
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

function normalizeQaJsonAnswer(answer: string | object): {
  version: string;
  answer_type: string;
  grounding: Record<string, boolean>;
  sections: Record<string, string[]>;
  followups: string[];
  disclaimer: string;
} | null {
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
    disclaimer: String(
      parsed.disclaimer || "仅用于投资知识学习，不构成投资建议。"
    ).trim(),
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
      sections.push({
        title: current.title,
        content,
      });
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

const QA_ANSWER_TYPE_LABELS: Record<string, string> = {
  concept: "Concept",
  operation_logic: "Trading Logic",
  correctness_check: "Analysis",
  stock_specific: "Stock Specific",
  simple: "Simple Q",
  general: "General",
};

function renderQaJsonLines(
  lines: string[],
  options: { risk?: boolean; compact?: boolean } = {}
): string {
  const items = toQaArray(lines);
  if (!items.length) return "";

  const { risk = false, compact = false } = options;
  const dot = risk ? "!" : "•";

  return `<div class="${compact ? "qa-json-lines compact" : "qa-json-lines"}">${items
    .map(
      (line, index) =>
        `<div class="qa-json-line ${risk ? "risk" : ""}"><span class="qa-json-line-dot">${
          compact ? index + 1 : dot
        }</span><span>${escapeHtml(line)}</span></div>`
    )
    .join("")}</div>`;
}

function renderQaStatusPills(model: {
  answer_type: string;
  grounding: Record<string, boolean>;
}): string {
  const typeLabel =
    QA_ANSWER_TYPE_LABELS[model.answer_type] || model.answer_type || "General";
  const pills = [`<span class="qa-json-pill primary">${escapeHtml(typeLabel)}</span>`];

  if (model.grounding.source_used)
    pills.push('<span class="qa-json-pill">From Transcript</span>');
  if (model.grounding.summary_used)
    pills.push('<span class="qa-json-pill">From Summary</span>');
  if (model.grounding.extension_used)
    pills.push('<span class="qa-json-pill accent">Extended</span>');
  if (model.grounding.source_summary_conflict)
    pills.push('<span class="qa-json-pill warn">Conflict</span>');

  return pills.join("");
}

function renderQaLogicSection(model: {
  sections: Record<string, string[]>;
}): string {
  const source = model.sections.source_explanation || [];
  const plain = model.sections.plain_language || [];
  if (!source.length && !plain.length) return "";

  return `<section class="qa-json-logic">
    ${
      source.length
        ? `<div class="qa-json-logic-pane source">
        <div class="qa-json-pane-head">
          <span class="qa-json-pane-icon">↳</span>
          <div>
            <div class="qa-json-pane-title">Based on Transcript</div>
            <div class="qa-json-pane-subtitle">Explains the source content</div>
          </div>
        </div>
        ${renderQaJsonLines(source)}
      </div>`
        : ""
    }
    ${source.length && plain.length ? '<div class="qa-json-flow-arrow">→</div>' : ""}
    ${
      plain.length
        ? `<div class="qa-json-logic-pane simple">
        <div class="qa-json-pane-head">
          <span class="qa-json-pane-icon">✦</span>
          <div>
            <div class="qa-json-pane-title">Plain Explanation</div>
            <div class="qa-json-pane-subtitle">Explains the logic in simple terms</div>
          </div>
        </div>
        ${renderQaJsonLines(plain)}
      </div>`
        : ""
    }
  </section>`;
}

function renderQaSupportSection(model: {
  sections: Record<string, string[]>;
}): string {
  const extra = model.sections.extra_context || [];
  const caution = model.sections.caution || [];
  if (!extra.length && !caution.length) return "";

  return `<section class="qa-json-support ${extra.length && caution.length ? "two" : "one"}">
    ${
      extra.length
        ? `<div class="qa-json-support-block extra">
        <div class="qa-json-support-title"><span>＋</span><span>扩展补充</span></div>
        ${renderQaJsonLines(extra)}
      </div>`
        : ""
    }
    ${
      caution.length
        ? `<div class="qa-json-support-block risk">
        <div class="qa-json-support-title"><span>!</span><span>注意事项</span></div>
        ${renderQaJsonLines(caution, { risk: true })}
      </div>`
        : ""
    }
  </section>`;
}

function renderQaFollowups(followups: string[]): string {
  if (!followups.length) return "";
  return `<div class="qa-json-followups">
    <span class="qa-json-followup-label">继续追问</span>
    ${followups
      .map(
        (item) =>
          `<button class="qa-followup-chip" data-followup="${escapeHtmlAttr(item)}">${escapeHtml(item)}</button>`
      )
      .join("")}
  </div>`;
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
    ...[
      "core_answer",
      "source_explanation",
      "plain_language",
      "extra_context",
      "caution",
    ].flatMap((key) => {
      const lines = model.sections[key] || [];
      if (!lines.length) return [];
      return [`\n【${labels[key]}】`, ...lines.map((line, index) => `${index + 1}. ${line}`)];
    }),
    ...(model.followups.length
      ? ["\n【继续追问】", ...model.followups.map((line, index) => `${index + 1}. ${line}`)]
      : []),
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
  const fallbackCore =
    core.length
      ? core
      : source.length
      ? source.slice(0, 2)
      : plain.length
      ? plain.slice(0, 2)
      : ["这个问题需要结合原文内容进一步判断。"];

  const fullText = qaJsonPlainText(model, question);
  const safeFullText = escapeHtmlAttr(fullText);
  const safeTitle = escapeHtmlAttr(
    question ? `Ask AI Answer · ${question}` : "Ask AI Answer"
  );

  return `<div class="qa-json-response">
    <div class="qa-json-top">
      <div>
        <div class="qa-json-eyebrow">AI Structured Answer</div>
        <div class="qa-json-title">答案逻辑板</div>
      </div>
      <div class="qa-json-pills">${renderQaStatusPills(model)}</div>
    </div>

    <section class="qa-json-core">
      <div class="qa-json-core-label">
        <span class="qa-json-core-mark">✦</span>
        <span>核心回答</span>
      </div>
      ${renderQaJsonLines(fallbackCore, { compact: true })}
    </section>

    ${renderQaLogicSection(model)}
    ${renderQaSupportSection(model)}

    <div class="qa-json-footer">
      <div class="qa-json-actions">
        <button class="qa-action-btn copy-full-qa" data-copy="${safeFullText}">Copy</button>
        <button class="qa-action-btn read-full-qa" data-text="${safeFullText}" data-title="${safeTitle}">Expand</button>
      </div>
      ${
        model.disclaimer
          ? `<div class="qa-json-disclaimer">${escapeHtml(model.disclaimer)}</div>`
          : ""
      }
    </div>

    ${renderQaFollowups(model.followups)}
  </div>`;
}

function renderLegacyQaAnswer(answer: string, question = ""): string {
  const raw = String(answer || "").trim();
  const sections = parseQaSections(raw);
  const map = new Map<string, string>();

  for (const section of sections) {
    const title = String(section.title || "")
      .replace(/[【】]/g, "")
      .replace(/[：:]$/, "")
      .trim();
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

function renderQaAnswer(answer: string, question = ""): string {
  const raw = (answer || "").trim();
  if (!raw) return '<div class="qa-fallback-card">暂无回答内容</div>';

  const model = normalizeQaJsonAnswer(raw);
  if (model && model.version === "qa_v1") {
    return renderQaJsonAnswer(model, question);
  }

  return renderLegacyQaAnswer(String(raw || ""), question);
}

function renderPlainBlock(content: string, max = 0): string {
  const lines = getLines(content, max);
  if (!lines.length)
    return '<div class="summary-panel-subtitle">暂无内容</div>';
  return lines.map((line) => `<div>${escapeHtml(line)}</div>`).join("");
}

function renderList(content: string, icon = "✓", max = 0): string {
  const lines = getLines(content, max);
  if (!lines.length)
    return '<div class="summary-panel-subtitle">暂无内容</div>';
  return `<div class="summary-list">${lines
    .map(
      (line) =>
        `<div class="summary-list-item"><span class="summary-list-icon">${escapeHtml(icon)}</span><span>${escapeHtml(line)}</span></div>`
    )
    .join("")}</div>`;
}

function renderFlowStep(index: string, title: string, content: string): string {
  if (!content) return "";
  return `<div class="summary-flow-step">
    <div class="summary-flow-index">${escapeHtml(index)}</div>
    <div>
      <div class="summary-flow-title">${escapeHtml(title)}</div>
      <div class="summary-flow-text">${renderPlainBlock(content, 2)}</div>
    </div>
  </div>`;
}

function renderKnowledgeNode(
  title: string,
  content: string,
  tag: string
): string {
  if (!content) return "";
  return `<div class="knowledge-node">
    <div class="knowledge-node-title"><span>${escapeHtml(title)}</span><span class="summary-pill">${escapeHtml(tag)}</span></div>
    <div class="knowledge-node-body">${renderPlainBlock(content)}</div>
  </div>`;
}

function renderDecisionCard(
  title: string,
  content: string,
  variant: "action" | "risk",
  icon: string
): string {
  if (!content) return "";
  return `<div class="decision-card ${variant}">
    <div class="decision-title"><span>${escapeHtml(title)}</span><span class="summary-list-icon">${escapeHtml(icon)}</span></div>
    ${renderList(content, icon)}
  </div>`;
}

function renderLearningCard(title: string, content: string): string {
  if (!content) return "";
  return `<div class="learning-card">
    <div class="learning-title">${escapeHtml(title)}</div>
    <div class="learning-body">${renderPlainBlock(content)}</div>
  </div>`;
}

function buildSummaryCards(summaryText: string): string {
  const sections = parseSummarySections(summaryText);
  if (!sections.length) {
    return '<div class="summary-empty-state">Waiting for summary...</div>';
  }

  const map = getSectionMap(sections);
  const coreTheme = getContent(map, "核心主题") || getContent(map, "摘要内容");
  const coreView = getContent(map, "核心观点");
  const knowledge = getContent(map, "关键知识点");
  const method = getContent(map, "方法论框架");
  const principles = getContent(map, "可复用原则");
  const scenarios = getContent(map, "适用场景");
  const actions = getContent(map, "可执行清单");
  const risks = [getContent(map, "风险提醒"), getContent(map, "失效场景")]
    .filter(Boolean)
    .join("\n");
  const mistakes = getContent(map, "新手误区");
  const notes = getContent(map, "学习笔记");
  const thinking = getContent(map, "思考方式总结");

  const knownTitles = new Set<string>(SUMMARY_ORDER);
  const extras = sections
    .filter((section) => !knownTitles.has(section.title))
    .map((section) => renderLearningCard(section.title, section.lines.join("\n").trim()))
    .join("");

  const heroPanel = `<section class="summary-panel hero-panel">
    <div class="summary-panel-head"><div><div class="summary-kicker">Conclusion Spine</div><div class="summary-panel-title">结论主线</div><div class="summary-panel-subtitle">先看主判断，再看它如何展开。</div></div></div>
    <div class="summary-panel-body">
      <div class="summary-hero-card">
        <div>
          <div class="summary-hero-eyebrow">AI Thesis</div>
          <div class="summary-hero-title">${escapeHtml(firstMeaningfulLine(coreTheme, "正在提炼核心主题"))}</div>
        </div>
        <div class="summary-hero-text">${renderPlainBlock(coreTheme, 4)}</div>
      </div>
      <div class="summary-flow">
        ${renderFlowStep("01", "核心观点", coreView)}
        ${renderFlowStep("02", "方法论框架", method)}
        ${renderFlowStep("03", "可复用原则", principles)}
      </div>
    </div>
  </section>`;

  const hubText = firstMeaningfulLine(
    coreView || coreTheme || knowledge,
    "这里会显示这段内容的中心判断"
  );
  const mapPanel = `<section class="summary-panel map-panel">
    <div class="summary-panel-head"><div><div class="summary-kicker">Knowledge Map</div><div class="summary-panel-title">知识地图</div><div class="summary-panel-subtitle">把内容拆成概念、方法、原则和适用边界。</div></div></div>
    <div class="summary-panel-body">
      <div class="knowledge-board">
        <div class="knowledge-hub"><div class="knowledge-hub-label">Central Idea</div><div class="knowledge-hub-text">${escapeHtml(hubText)}</div></div>
        ${renderKnowledgeNode("关键知识点", knowledge, "Know")}
        ${renderKnowledgeNode("方法论框架", method, "Method")}
        ${renderKnowledgeNode("可复用原则", principles, "Principle")}
        ${renderKnowledgeNode("适用场景", scenarios, "Context")}
      </div>
    </div>
  </section>`;

  const actionPanel = `<section class="summary-panel action-panel">
    <div class="summary-panel-head"><div><div class="summary-kicker">Action Dock</div><div class="summary-panel-title">下一步行动</div><div class="summary-panel-subtitle">把内容转成可执行动作，只保留真正值得做的事。</div></div></div>
    <div class="summary-panel-body">
      <div class="decision-stack">${renderDecisionCard("可执行清单", actions || coreView, "action", "✓")}</div>
    </div>
  </section>`;

  const riskItems = [
    renderDecisionCard("风险提醒 / 失效场景", risks, "risk", "!"),
    renderDecisionCard("新手误区", mistakes, "risk", "✕"),
  ]
    .filter(Boolean)
    .join("");

  const riskPanel = riskItems
    ? `<section class="summary-panel risk-radar-panel">
    <div class="summary-panel-head"><div><div class="summary-kicker">Risk Radar</div><div class="summary-panel-title">风险雷达</div><div class="summary-panel-subtitle">单独看风险、边界条件和常见误区。</div></div></div>
    <div class="summary-panel-body"><div class="risk-radar-grid">${riskItems}</div></div>
  </section>`
    : "";

  const learningItems = [
    renderLearningCard("学习笔记", notes),
    renderLearningCard("思考方式总结", thinking),
    extras,
  ]
    .filter(Boolean)
    .join("");

  const learningPanel = learningItems
    ? `<section class="summary-panel learning-panel">
    <div class="summary-panel-head"><div><div class="summary-kicker">Reflection</div><div class="summary-panel-title">学习沉淀</div><div class="summary-panel-subtitle">方便复盘、记录和二次吸收。</div></div></div>
    <div class="summary-panel-body"><div class="learning-grid">${learningItems}</div></div>
  </section>`
    : "";

  return heroPanel + mapPanel + actionPanel + riskPanel + learningPanel;
}

interface QaItem {
  id: string;
  question: string;
  answerHtml: string;
}

function App() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const esRef = useRef<EventSource | null>(null);

  const [phase, setPhase] = useState<Phase>("idle");
  const [transcript, setTranscript] = useState("");
  const [polished, setPolished] = useState("");
  const [summary, setSummary] = useState("");
  const [taskId, setTaskId] = useState("");
  const [error, setError] = useState("");
  const [isRawView, setIsRawView] = useState(false);
  const [qaInput, setQaInput] = useState("");
  const [qaLoading, setQaLoading] = useState(false);
  const [qaItems, setQaItems] = useState<QaItem[]>([]);
  const [showReader, setShowReader] = useState(false);
  const [readerText, setReaderText] = useState("");
  const [readerTitle, setReaderTitle] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [collapsedQaItems, setCollapsedQaItems] = useState<Record<string, boolean>>({});

  const currentStep =
    phase === "idle"
      ? 0
      : phase === "converting"
      ? 1
      : phase === "transcribing"
      ? 2
      : phase === "polishing"
      ? 3
      : 4;

  const toggleCollapse = useCallback((name: string) => {
    setCollapsed((prev) => ({ ...prev, [name]: !prev[name] }));
  }, []);

  const toggleQaItemCollapse = useCallback((id: string) => {
    setCollapsedQaItems((prev) => ({ ...prev, [id]: !prev[id] }));
  }, []);

  const handleFileSelected = useCallback(async (file: File) => {
    setPhase("converting");
    setTranscript("");
    setPolished("");
    setSummary("");
    setError("");
    setTaskId("");
    setQaItems([]);
    setIsRawView(false);
    setCollapsed({});
    setCollapsedQaItems({});

    try {
      const id = await uploadFile(file);
      setTaskId(id);

      const es = createSSEConnection(id, {
        onEvent: (event: SSEEvent) => {
          switch (event.type) {
            case "transcribe_start":
              setPhase("transcribing");
              break;
            case "chunk":
              setTranscript(event.text || "");
              setPhase("transcribing");
              break;
            case "transcribe_done":
              setPhase("polishing");
              break;
            case "polish_start":
              setPhase("polishing");
              break;
            case "polish_char":
              setPolished(event.text || "");
              setPhase("polishing");
              break;
            case "polish_done":
              setPolished((prev) => event.polished_text || event.text || prev);
              setPhase("summarizing");
              break;
            case "summary_start":
              setPhase("summarizing");
              break;
            case "summary_char":
              setSummary(event.text || "");
              setPhase("summarizing");
              break;
            case "summary_done":
              setSummary((prev) => event.summary_text || event.text || prev);
              setPolished((prev) => event.polished_text || prev);
              break;
            case "done":
              setPolished((prev) => event.polished_text || prev);
              setSummary((prev) => event.summary_text || prev);
              setPhase("done");
              break;
            case "error":
              setError(event.error || "Unknown error");
              setPhase("error");
              break;
          }
        },
        onError: (err) => {
          setError(err);
          setPhase("error");
        },
        onDone: () => {
          setPhase("done");
        },
      });

      esRef.current = es;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("error");
    }
  }, []);

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFileSelected(file);
    },
    [handleFileSelected]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const file = e.dataTransfer.files[0];
      if (file) handleFileSelected(file);
    },
    [handleFileSelected]
  );

  const handleExport = useCallback(async () => {
    if (!taskId || phase !== "done") return;
    try {
      await exportMarkdown(taskId);
    } catch {
      setError("Export failed");
    }
  }, [taskId, phase]);

  const handleQASubmit = useCallback(async () => {
    if (!taskId || !qaInput.trim() || qaLoading) return;
    setQaLoading(true);
    try {
      const answer = await askQuestion(taskId, qaInput.trim());
      const id = `qa-item-${Date.now()}`;
      const newItem: QaItem = {
        id,
        question: qaInput.trim(),
        answerHtml: renderQaAnswer(answer, qaInput.trim()),
      };
      setQaItems((prev) => [newItem, ...prev]);
      setCollapsedQaItems((prev) => ({ ...prev, [id]: false }));
      setQaInput("");
    } catch {
      setError("Q&A request failed");
    } finally {
      setQaLoading(false);
    }
  }, [taskId, qaInput, qaLoading]);

  const handleQAKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleQASubmit();
      }
    },
    [handleQASubmit]
  );

  const handleQAChipClick = useCallback((prompt: string) => {
    setQaInput(prompt);
  }, []);

  const handleCopyText = useCallback((text: string) => {
    navigator.clipboard.writeText(text);
  }, []);

  const handleOpenReader = useCallback((text: string, title: string) => {
    setReaderText(text);
    setReaderTitle(title);
    setShowReader(true);
  }, []);

  const handleDocumentClick = useCallback(
    (e: MouseEvent) => {
      const target = e.target as HTMLElement;

      const chip = target.closest(".qa-followup-chip") as HTMLButtonElement | null;
      if (chip) {
        const prompt = chip.dataset.followup;
        if (prompt) handleQAChipClick(prompt);
        return;
      }

      const readBtn = target.closest(".read-full-qa") as HTMLButtonElement | null;
      if (readBtn) {
        const text = readBtn.dataset.text || "";
        const title = readBtn.dataset.title || "Ask AI Answer";
        handleOpenReader(text, title);
        return;
      }

      const copyBtn = target.closest(".copy-full-qa") as HTMLButtonElement | null;
      if (copyBtn) {
        const text = copyBtn.dataset.copy || "";
        handleCopyText(text);
      }
    },
    [handleQAChipClick, handleOpenReader, handleCopyText]
  );

  useEffect(() => {
    document.addEventListener("click", handleDocumentClick);
    return () => document.removeEventListener("click", handleDocumentClick);
  }, [handleDocumentClick]);

  useEffect(() => {
    return () => {
      esRef.current?.close();
    };
  }, []);

  const progressPct =
    phase === "idle"
      ? 0
      : phase === "converting"
      ? 15
      : phase === "transcribing"
      ? 40
      : phase === "polishing"
      ? 65
      : phase === "summarizing"
      ? 85
      : 100;

  const phaseLabel =
    phase === "idle"
      ? "Waiting for upload"
      : phase === "converting"
      ? "Converting media..."
      : phase === "transcribing"
      ? "Transcribing..."
      : phase === "polishing"
      ? "AI polishing..."
      : phase === "summarizing"
      ? "AI summarizing..."
      : phase === "done"
      ? "Done"
      : "Error";

  const summaryCardsHtml =
    phase !== "idle" && phase !== "error" && summary
      ? buildSummaryCards(summary)
      : "";

  const showResults = phase !== "idle" && phase !== "error";
  const showError = phase === "error";

  return (
    <div className="container">
      <style>{QA_STYLE_FIX}</style>
      <h1>MP4 to Text</h1>
      <p className="subtitle">
        Upload video, transcribe automatically, polish with AI, and generate a clean
        summary for trading and investing content.
      </p>

      <div className="step-bar">
        {STEPS.map((label, i) => (
          <div
            key={label}
            className={`step ${
              i < currentStep ? "done" : i === currentStep ? "active" : ""
            }`}
          >
            {label}
          </div>
        ))}
      </div>

      {phase === "idle" && (
        <div
          className="upload-box"
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
        >
          <div className="upload-icon">📁</div>
          <div className="upload-text">Choose a media file or drag it here</div>
          <div className="upload-hint">
            Supports MP4, MOV, AVI, MP3, WAV, M4A and other audio/video formats
          </div>
        </div>
      )}
      <input
        type="file"
        ref={fileInputRef}
        accept="video/*,audio/mpeg,audio/wav,audio/mp3,.mp3"
        style={{ display: "none" }}
        onChange={handleFileChange}
      />

      {phase !== "idle" && (
        <div
          id="progressInfo"
          style={{
            display: "block",
            marginBottom: "16px",
            fontSize: "13px",
            color: "#71767b",
          }}
        >
          <span className="phase">{phaseLabel}</span>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${progressPct}%` }}></div>
          </div>
        </div>
      )}

      {showError && (
        <div
          style={{
            background: "rgba(255,255,255,0.76)",
            border: "1px solid rgba(245,30,30,0.2)",
            borderRadius: "24px",
            padding: "24px",
            marginBottom: "16px",
            color: "#f4212e",
            fontSize: "14px",
          }}
        >
          ❌ Error: {error}
          <br />
          <button
            onClick={() => setPhase("idle")}
            style={{
              marginTop: "12px",
              background: "rgba(0,113,227,0.08)",
              color: "#0071e3",
              border: "1px solid rgba(0,113,227,0.2)",
              borderRadius: "999px",
              padding: "8px 16px",
              fontSize: "13px",
              cursor: "pointer",
            }}
          >
            Retry
          </button>
        </div>
      )}

      {showResults && (
        <div id="resultsArea">
          <div className="columns">
            <div className="result-box">
              <div
                className="result-header"
                onClick={() => toggleCollapse("transcript")}
              >
                <span className="result-title">
                  <span className="icon">📝</span>Transcript
                </span>
                <div className="result-meta">
                  <span className="char-count">{transcript.length} chars</span>
                  <button
                    className="copy-btn"
                    title="Copy transcript"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleCopyText(transcript);
                    }}
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                      <rect x="9" y="9" width="10" height="10" rx="2" stroke="currentColor" strokeWidth="1.8"/>
                      <rect x="5" y="5" width="10" height="10" rx="2" stroke="currentColor" strokeWidth="1.8" opacity="0.75"/>
                    </svg>
                  </button>
                  <svg
                    className={`result-toggle ${collapsed.transcript ? "" : "open"}`}
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                  >
                    <polyline points="6 9 12 15 18 9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </div>
              </div>
              <div className={`result-body-wrap ${collapsed.transcript ? "collapsed" : "open"}`}>
                <div className="result-body">{transcript}</div>
              </div>
            </div>

            <div className="result-box">
              <div
                className="result-header"
                onClick={() => toggleCollapse("polish")}
              >
                <span className="result-title">
                  <span className="icon">✨</span>AI Polish
                </span>
                <div className="result-meta">
                  <span className="char-count">{polished.length} chars</span>
                  <button
                    className="expand-btn"
                    title="Open in reading mode"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleOpenReader(polished, "Reading Mode");
                    }}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                      <polyline points="15 3 21 3 21 9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                      <polyline points="9 21 3 21 3 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                      <line x1="21" y1="3" x2="14" y2="10" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
                      <line x1="3" y1="21" x2="10" y2="14" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
                    </svg>
                    Read
                  </button>
                  <button
                    className="copy-btn"
                    title="Copy polished text"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleCopyText(polished);
                    }}
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                      <rect x="9" y="9" width="10" height="10" rx="2" stroke="currentColor" strokeWidth="1.8"/>
                      <rect x="5" y="5" width="10" height="10" rx="2" stroke="currentColor" strokeWidth="1.8" opacity="0.75"/>
                    </svg>
                  </button>
                  <svg
                    className={`result-toggle ${collapsed.polish ? "" : "open"}`}
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                  >
                    <polyline points="6 9 12 15 18 9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </div>
              </div>
              <div className={`result-body-wrap ${collapsed.polish ? "collapsed" : "open"}`}>
                <div className="result-body">{polished}</div>
              </div>
            </div>
          </div>

          <div className="summary-box">
            <div
              className="result-header"
              onClick={() => toggleCollapse("summary")}
            >
              <span className="result-title">
                <span className="icon">🧠</span>AI Summary
              </span>
              <div className="result-meta">
                <button
                  className={`toggle-view-btn ${isRawView ? "active" : ""}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    setIsRawView((v) => !v);
                  }}
                >
                  {isRawView ? "Cards" : "Raw"}
                </button>
                <button
                  className="copy-btn summary-master-copy"
                  title="Copy full summary"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleCopyText(summary);
                  }}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <rect x="9" y="9" width="10" height="10" rx="2" stroke="currentColor" strokeWidth="1.8"/>
                    <rect x="5" y="5" width="10" height="10" rx="2" stroke="currentColor" strokeWidth="1.8" opacity="0.75"/>
                  </svg>
                </button>
                <button
                  className="export-btn"
                  disabled={phase !== "done"}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleExport();
                  }}
                >
                  Export MD
                </button>
                <svg
                  className={`result-toggle ${collapsed.summary ? "" : "open"}`}
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                >
                  <polyline points="6 9 12 15 18 9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
            </div>
            <div className={`result-body-wrap ${collapsed.summary ? "collapsed" : "open"}`}>
              <div className={`summary-stage ${isRawView ? "raw-mode" : ""}`}>
                <div
                  className="summary-workspace"
                  dangerouslySetInnerHTML={{ __html: summaryCardsHtml }}
                />
                <div className="summary-raw-view">{summary}</div>
              </div>
            </div>
          </div>

          <div className="qa-section">
            <div className="result-box qa-box">
              <div className="result-header" onClick={() => toggleCollapse("qa")}>
                <span className="result-title">
                  <span className="icon">💬</span>Ask AI
                </span>
                <div className="result-meta">
                  <span className="char-count">{qaItems.length} answers</span>
                  <svg
                    className={`result-toggle ${collapsed.qa ? "" : "open"}`}
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                  >
                    <polyline points="6 9 12 15 18 9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </div>
              </div>
              <div className={`result-body-wrap ${collapsed.qa ? "collapsed" : "open"}`}>
                <div className="qa-body">
                  <div className="qa-input-wrap">
                    <textarea
                      className="qa-input"
                      value={qaInput}
                      onChange={(e) => setQaInput(e.target.value)}
                      onKeyDown={handleQAKeyDown}
                      placeholder="Ask about the transcript, summary, or logic..."
                    />
                    <button
                      className="qa-submit"
                      disabled={!taskId || qaLoading || !qaInput.trim()}
                      onClick={handleQASubmit}
                    >
                      {qaLoading ? "Sending..." : "Send"}
                    </button>
                  </div>

                  <div className="qa-list">
                    {qaItems.map((item) => {
                      const isCollapsed = collapsedQaItems[item.id] ?? false;
                      return (
                        <div key={item.id} className="qa-item">
                          <div
                            className="qa-item-header"
                            onClick={() => toggleQaItemCollapse(item.id)}
                          >
                            <div className={`qa-item-q-text ${isCollapsed ? "" : "expanded"}`}>
                              {item.question}
                            </div>
                            <svg
                              className={`qa-item-toggle ${isCollapsed ? "" : "open"}`}
                              width="16"
                              height="16"
                              viewBox="0 0 24 24"
                              fill="none"
                            >
                              <polyline points="6 9 12 15 18 9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                            </svg>
                          </div>
                          <div className={`qa-item-body ${isCollapsed ? "" : "open"}`}>
                            <div className="qa-answer-body">
                              <div
                                className="qa-answer"
                                dangerouslySetInnerHTML={{ __html: item.answerHtml }}
                              />
                            </div>
                          </div>
                        </div>
                      );
                    })}
                    {!qaItems.length && (
                      <div className="qa-empty">
                        Ask a question about the transcript or summary to get a structured answer.
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {showReader && (
        <div className="reader-overlay" onClick={() => setShowReader(false)}>
          <div className="reader-modal" onClick={(e) => e.stopPropagation()}>
            <div className="reader-header">
              <div className="reader-title">{readerTitle}</div>
              <button className="reader-close" onClick={() => setShowReader(false)}>
                ✕
              </button>
            </div>
            <div className="reader-content">{readerText}</div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
