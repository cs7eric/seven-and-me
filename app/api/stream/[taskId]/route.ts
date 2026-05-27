import { NextRequest } from 'next/server';
import { taskStore } from '@/lib/task-store';

export const dynamic = 'force-dynamic';

export async function GET(
  request: NextRequest,
  { params }: { params: { taskId: string } }
) {
  const taskId = params.taskId;

  const stream = new ReadableStream({
    start(controller) {
      const encoder = new TextEncoder();

      const send = (event: string, data: object) => {
        const payload = JSON.stringify({ type: event, ...data });
        controller.enqueue(encoder.encode(`data: ${payload}\n\n`));
      };

      let lastState = '';
      let resolved = false;

      const interval = setInterval(() => {
        const store = taskStore.get(taskId);
        if (!store) return;

        const stateKey = `${store.status}|${store.transcript}|${store.polished}|${store.summary}`;

        if (stateKey !== lastState) {
          lastState = stateKey;

          if (store.status === 'transcribing' && store.transcript) {
            send('chunk', { text: store.transcript });
          } else if (store.status === 'polishing') {
            if (store.polished) {
              send('polish_chunk', { text: store.polished });
            }
          } else if (store.status === 'summarizing') {
            if (store.summary) {
              send('summary_chunk', { text: store.summary });
            }
          }

          if (store.status === 'done') {
            send('done', {});
            resolved = true;
            clearInterval(interval);
            controller.close();
          } else if (store.status === 'error') {
            send('error', { error: store.error || 'Unknown error' });
            resolved = true;
            clearInterval(interval);
            controller.close();
          }
        }
      }, 300);

      // Timeout after 10 minutes
      setTimeout(() => {
        if (!resolved) {
          send('error', { error: '处理超时' });
          clearInterval(interval);
          controller.close();
        }
      }, 600000);
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}