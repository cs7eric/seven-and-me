import type { SummarySection } from "./types";
import { SUMMARY_TITLES } from "./types";

export function parseSummarySections(text: string): SummarySection[] {
  const lines = String(text || "").split("\n");
  const sections: SummarySection[] = [];
  let current: SummarySection | null = null;

  for (const line of lines) {
    const trimmed = line.trim();
    const title = trimmed
      .replace(/^#+\s*/, "")
      .replace(/[：:]$/, "")
      .trim();

    if ((SUMMARY_TITLES as readonly string[]).includes(title)) {
      if (current) sections.push(current);
      current = { title, lines: [] };
      continue;
    }

    if (!current) {
      if (trimmed) current = { title: "摘要内容", lines: [line] };
      continue;
    }
    current.lines.push(line);
  }

  if (current) sections.push(current);
  return sections;
}

export function getSectionMap(
  sections: SummarySection[]
): Map<string, string> {
  const map = new Map<string, string>();
  sections.forEach((section) => {
    const existing = map.get(section.title);
    const content = section.lines.join("\n").trim();
    if (!existing) map.set(section.title, content);
    else map.set(section.title, [existing, content].filter(Boolean).join("\n"));
  });
  return map;
}

export function cleanSummaryLine(line: string): string {
  return String(line || "")
    .trim()
    .replace(/^[-•*]\s*/, "")
    .replace(/^\d+[.、)]\s*/, "")
    .replace(/^\[\s?]/, "")
    .replace(/^\[x\]\s*/i, "")
    .trim();
}

export function getLines(content: string, max = 0): string[] {
  const lines = String(content || "")
    .split("\n")
    .map(cleanSummaryLine)
    .filter(Boolean);
  return max ? lines.slice(0, max) : lines;
}

export function getContent(map: Map<string, string>, title: string): string {
  return map.get(title) || "";
}

export function firstMeaningfulLine(
  content: string,
  fallback = "暂无内容"
): string {
  return getLines(content, 1)[0] || fallback;
}