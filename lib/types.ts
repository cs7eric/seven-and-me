export type TaskStatus =
  | 'idle'
  | 'converting'
  | 'transcribing'
  | 'polishing'
  | 'summarizing'
  | 'done'
  | 'error';

export interface TaskData {
  status: TaskStatus;
  transcript: string;
  polished: string;
  summary: string;
  error?: string;
}

export type SSEEvent =
  | { type: 'transcribe_start' }
  | { type: 'chunk'; text: string }
  | { type: 'transcribe_done' }
  | { type: 'polish_start' }
  | { type: 'polish_done'; polished_text: string }
  | { type: 'polish_chunk'; text: string }
  | { type: 'summary_start' }
  | { type: 'summary_done'; summary_text: string }
  | { type: 'summary_chunk'; text: string }
  | { type: 'done' }
  | { type: 'error'; error: string };