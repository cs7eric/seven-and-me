import type { TransferProgress } from "./types";

export interface MP4HistoryQAItem {
  id: string;
  question: string;
  answer: string;
  created_at: string;
}

export interface MP4HistoryMetadata {
  title?: string;
  categories?: string[];
  tags?: string[];
  platform?: string;
  duration?: number;
  noteType?: string;
  source_url?: string;
  download_url?: string;
  [key: string]: unknown;
}

export interface MP4HistoryTaskData {
  task_id: string;
  status: string;
  transcript: string;
  polished: string;
  summary: string;
  metadata: MP4HistoryMetadata;
  file_name: string;
  error?: string | null;
  download_progress?: TransferProgress;
  intake_progress?: TransferProgress;
  qa_items?: MP4HistoryQAItem[];
}

export interface MP4HistoryRecord {
  id: string;
  type: "mp4_parse";
  version: number;
  created_at: string;
  updated_at: string;
  title: string;
  task: MP4HistoryTaskData;
}

export interface MP4HistoryListItem {
  id: string;
  title: string;
  created_at: string;
  task_id: string;
  status: string;
  file_name?: string;
  data_file: string;
}

export interface ReferenceRootIndex {
  version: number;
  updated_at: string | null;
  types: Record<string, {
    title: string;
    index_file: string;
    data_dir: string;
    count: number;
  }>;
}
