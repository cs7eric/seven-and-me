import { getLines, firstMeaningfulLine, getContent, getSectionMap, parseSummarySections } from "../../../lib/summary-utils";
import { escapeHtml } from "./html";
import { SUMMARY_ORDER } from "../constants";

function renderPlainBlock(content: string, max = 0): string {
  const lines = getLines(content, max);
  if (!lines.length) {
    return '<div class="summary-panel-subtitle">暂无内容</div>';
  }
  return lines.map((line) => `<div>${escapeHtml(line)}</div>`).join("");
}

function renderList(content: string, icon = "✓", max = 0): string {
  const lines = getLines(content, max);
  if (!lines.length) {
    return '<div class="summary-panel-subtitle">暂无内容</div>';
  }
  return `<div class="summary-list">${lines
    .map(
      (line) =>
        `<div class="summary-list-item"><span class="summary-list-icon">${escapeHtml(icon)}</span><span>${escapeHtml(line)}</span></div>`
    )
    .join("")}</div>`;
}

function renderFlowStep(index: string, title: string, content: string): string {
  if (!content) return "";
  return `<div class="summary-flow-step"><div class="summary-flow-index">${escapeHtml(index)}</div><div><div class="summary-flow-title">${escapeHtml(title)}</div><div class="summary-flow-text">${renderPlainBlock(content, 2)}</div></div></div>`;
}

function renderKnowledgeNode(title: string, content: string, tag: string): string {
  if (!content) return "";
  return `<div class="knowledge-node"><div class="knowledge-node-title"><span>${escapeHtml(title)}</span><span class="summary-pill">${escapeHtml(tag)}</span></div><div class="knowledge-node-body">${renderPlainBlock(content)}</div></div>`;
}

function renderDecisionCard(
  title: string,
  content: string,
  variant: "action" | "risk",
  icon: string
): string {
  if (!content) return "";
  return `<div class="decision-card ${variant}"><div class="decision-title"><span>${escapeHtml(title)}</span><span class="summary-list-icon">${escapeHtml(icon)}</span></div>${renderList(content, icon)}</div>`;
}

function renderLearningCard(title: string, content: string): string {
  if (!content) return "";
  return `<div class="learning-card"><div class="learning-title">${escapeHtml(title)}</div><div class="learning-body">${renderPlainBlock(content)}</div></div>`;
}

export function buildSummaryCards(summaryText: string): string {
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
  const risks = [getContent(map, "风险提醒"), getContent(map, "失效场景")].filter(Boolean).join("\n");
  const mistakes = getContent(map, "新手误区");
  const notes = getContent(map, "学习笔记");
  const thinking = getContent(map, "思考方式总结");

  const knownTitles = new Set<string>(SUMMARY_ORDER);
  const extras = sections
    .filter((section) => !knownTitles.has(section.title))
    .map((section) => renderLearningCard(section.title, section.lines.join("\n").trim()))
    .join("");

  const heroPanel = `<section class="summary-panel hero-panel"><div class="summary-panel-head"><div><div class="summary-kicker">Conclusion Spine</div><div class="summary-panel-title">结论主线</div><div class="summary-panel-subtitle">先看主判断，再看它如何展开。</div></div></div><div class="summary-panel-body"><div class="summary-hero-card"><div><div class="summary-hero-eyebrow">AI Thesis</div><div class="summary-hero-title">${escapeHtml(firstMeaningfulLine(coreTheme, "正在提炼核心主题"))}</div></div><div class="summary-hero-text">${renderPlainBlock(coreTheme, 4)}</div></div><div class="summary-flow">${renderFlowStep("01", "核心观点", coreView)}${renderFlowStep("02", "方法论框架", method)}${renderFlowStep("03", "可复用原则", principles)}</div></div></section>`;

  const hubText = firstMeaningfulLine(coreView || coreTheme || knowledge, "这里会显示这段内容的中心判断");
  const mapPanel = `<section class="summary-panel map-panel"><div class="summary-panel-head"><div><div class="summary-kicker">Knowledge Map</div><div class="summary-panel-title">知识地图</div><div class="summary-panel-subtitle">把内容拆成概念、方法、原则和适用边界。</div></div></div><div class="summary-panel-body"><div class="knowledge-board"><div class="knowledge-hub"><div class="knowledge-hub-label">Central Idea</div><div class="knowledge-hub-text">${escapeHtml(hubText)}</div></div>${renderKnowledgeNode("关键知识点", knowledge, "Know")}${renderKnowledgeNode("方法论框架", method, "Method")}${renderKnowledgeNode("可复用原则", principles, "Principle")}${renderKnowledgeNode("适用场景", scenarios, "Context")}</div></div></section>`;

  const actionPanel = `<section class="summary-panel action-panel"><div class="summary-panel-head"><div><div class="summary-kicker">Action Dock</div><div class="summary-panel-title">下一步行动</div><div class="summary-panel-subtitle">把内容转成可执行动作，只保留真正值得做的事。</div></div></div><div class="summary-panel-body"><div class="decision-stack">${renderDecisionCard("可执行清单", actions || coreView, "action", "✓")}</div></div></section>`;

  const riskItems = [
    renderDecisionCard("风险提醒 / 失效场景", risks, "risk", "!"),
    renderDecisionCard("新手误区", mistakes, "risk", "✕"),
  ].filter(Boolean).join("");

  const riskPanel = riskItems
    ? `<section class="summary-panel risk-radar-panel"><div class="summary-panel-head"><div><div class="summary-kicker">Risk Radar</div><div class="summary-panel-title">风险雷达</div><div class="summary-panel-subtitle">单独看风险、边界条件和常见误区。</div></div></div><div class="summary-panel-body"><div class="risk-radar-grid">${riskItems}</div></div></section>`
    : "";

  const learningItems = [
    renderLearningCard("学习笔记", notes),
    renderLearningCard("思考方式总结", thinking),
    extras,
  ].filter(Boolean).join("");

  const learningPanel = learningItems
    ? `<section class="summary-panel learning-panel"><div class="summary-panel-head"><div><div class="summary-kicker">Reflection</div><div class="summary-panel-title">学习沉淀</div><div class="summary-panel-subtitle">方便复盘、记录和二次吸收。</div></div></div><div class="summary-panel-body"><div class="learning-grid">${learningItems}</div></div></section>`
    : "";

  return heroPanel + mapPanel + actionPanel + riskPanel + learningPanel;
}
