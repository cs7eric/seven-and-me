export type Phase = "idle" | "converting" | "transcribing" | "polishing" | "summarizing" | "done" | "error";

export interface TaskState {
  status: Phase;
  transcript: string;
  polished: string;
  summary: string;
  metadata: PostMetadata;
  error?: string;
}

export interface PostMetadata {
  title: string;
  categories: string[];
  tags: string[];
}

export interface SSEEvent {
  type:
    | "transcribe_start"
    | "chunk"
    | "transcribe_done"
    | "polish_start"
    | "polish_char"
    | "polish_done"
    | "summary_start"
    | "summary_char"
    | "summary_done"
    | "done"
    | "error";
  text?: string;
  polished_text?: string;
  summary_text?: string;
  raw_text?: string;
  char_count?: number;
  metadata?: PostMetadata;
  task_id?: string;
  error?: string;
  progress?: number;
}

export interface QAResponse {
  answer: string;
}

export const API_BASE = "http://localhost:5000";

export const PHASE_LABELS: Record<Phase, string> = {
  idle: "等待上传",
  converting: "转换音视频中...",
  transcribing: "转写中...",
  polishing: "AI 润色中...",
  summarizing: "AI 摘要生成中...",
  done: "完成",
  error: "处理失败",
};

export const PHASE_PROGRESS: Record<Phase, number> = {
  idle: 0,
  converting: 15,
  transcribing: 40,
  polishing: 65,
  summarizing: 85,
  done: 100,
  error: 100,
};

export const SUMMARY_TITLES = [
  "核心主题",
  "核心观点",
  "关键知识点",
  "方法论框架",
  "可复用原则",
  "适用场景",
  "失效场景",
  "风险提醒",
  "新手误区",
  "学习笔记",
  "可执行清单",
  "思考方式总结",
] as const;

export interface SummarySection {
  title: string;
  lines: string[];
}