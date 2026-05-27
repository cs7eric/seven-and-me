import type { NextRequest } from 'next/server';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { taskStore } from '@/lib/task-store';
import { transcribe_streaming, convertVideoToAudio } from '@/lib/transcriber';
import { polish_stream, summarize_stream } from '@/lib/polisher';
import type { SSEEvent } from '@/lib/types';

async function processTask(taskId: string, filePath: string): Promise<void> {
  const audioPath = path.join(os.tmpdir(), `${taskId}_audio.wav`);

  const sendUpdate = (event: SSEEvent) => {
    // Update taskStore — the stream route will push these
  };

  try {
    // Convert video to audio
    taskStore.set(taskId, { status: 'converting', transcript: '', polished: '', summary: '' });
    await convertVideoToAudio(filePath, audioPath);

    // Transcribe with streaming
    taskStore.set(taskId, { status: 'transcribing', transcript: '', polished: '', summary: '' });

    let fullTranscript = '';
    const transcript = await transcribe_streaming(
      audioPath,
      30,
      {
        onChunk: (_idx, text, _isFinal) => {
          fullTranscript = text;
          taskStore.set(taskId, { status: 'transcribing', transcript: text, polished: '', summary: '' });
        },
      }
    );

    taskStore.set(taskId, { status: 'polishing', transcript, polished: '', summary: '' });

    // Polish with streaming
    let polishedText = '';
    await polish_stream(transcript, (text) => {
      polishedText = text;
      taskStore.set(taskId, { status: 'polishing', transcript, polished: text, summary: '' });
    });

    taskStore.set(taskId, { status: 'summarizing', transcript, polished: polishedText, summary: '' });

    // Summarize with streaming
    let summaryText = '';
    await summarize_stream(polishedText, (text) => {
      summaryText = text;
      taskStore.set(taskId, { status: 'summarizing', transcript, polished: polishedText, summary: text });
    });

    taskStore.set(taskId, { status: 'done', transcript, polished: polishedText, summary: summaryText });
  } catch (err: unknown) {
    const error = err instanceof Error ? err.message : String(err);
    console.error(`[Task ${taskId}] 错误:`, error);
    taskStore.set(taskId, { status: 'error', transcript: '', polished: '', summary: '', error });
  } finally {
    try {
      if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
      if (fs.existsSync(audioPath)) fs.unlinkSync(audioPath);
    } catch {}
  }
}

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const file = formData.get('file') as File | null;

    if (!file) {
      return Response.json({ error: 'No file provided' }, { status: 400 });
    }

    const taskId = crypto.randomUUID();
    const tmpPath = path.join(os.tmpdir(), `${taskId}_video.mp4`);

    const buffer = Buffer.from(await file.arrayBuffer());
    fs.writeFileSync(tmpPath, buffer);

    processTask(taskId, tmpPath).catch(console.error);

    return Response.json({ taskId });
  } catch (err: unknown) {
    const error = err instanceof Error ? err.message : String(err);
    return Response.json({ error }, { status: 500 });
  }
}