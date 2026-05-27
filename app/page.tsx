'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import UploadZone from '@/components/UploadZone';
import StepBar from '@/components/StepBar';
import TranscriptPanel from '@/components/TranscriptPanel';
import PolishPanel from '@/components/PolishPanel';
import SummaryPanel from '@/components/SummaryPanel';
import ProgressBar from '@/components/ProgressBar';

type Phase = 'idle' | 'converting' | 'transcribing' | 'polishing' | 'summarizing' | 'done' | 'error';

const PHASE_LABELS: Record<Phase, string> = {
  idle: '等待上传',
  converting: '转换音视频中...',
  transcribing: '转写中...',
  polishing: 'AI 润色中...',
  summarizing: 'AI 摘要生成中...',
  done: '完成',
  error: '处理失败',
};

const PHASE_PROGRESS: Record<Phase, number> = {
  idle: 0,
  converting: 15,
  transcribing: 40,
  polishing: 65,
  summarizing: 85,
  done: 100,
  error: 100,
};

const STEP_LABELS = ['上传文件', '转换音频', '语音转写', 'AI润色', '摘要总结'];

export default function HomePage() {
  const [phase, setPhase] = useState<Phase>('idle');
  const [transcript, setTranscript] = useState('');
  const [polished, setPolished] = useState('');
  const [summary, setSummary] = useState('');
  const [error, setError] = useState('');
  const [fileName, setFileName] = useState('');
  const eventSourceRef = useRef<EventSource | null>(null);
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const lastStateRef = useRef('');

  const stepIndex = Object.keys(PHASE_LABELS).indexOf(phase) - 1;
  const currentStep = phase === 'idle' ? 0 :
    phase === 'converting' ? 1 :
    phase === 'transcribing' ? 2 :
    phase === 'polishing' ? 3 :
    phase === 'summarizing' || phase === 'done' || phase === 'error' ? 4 : 0;

  const connectAndPoll = useCallback((taskId: string) => {
    // Polling-based SSE simulation since the backend doesn't have proper SSE push
    pollIntervalRef.current = setInterval(async () => {
      try {
        const es = new EventSource(`/api/stream/${taskId}`);

        es.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            const stateKey = `${data.type}|${data.text || ''}|${data.polished_text || ''}|${data.summary_text || ''}`;

            if (stateKey === lastStateRef.current) return;
            lastStateRef.current = stateKey;

            switch (data.type) {
              case 'chunk':
                setTranscript(data.text || '');
                setPhase('transcribing');
                break;
              case 'polish_chunk':
                setPolished(data.text || '');
                setPhase('polishing');
                break;
              case 'summary_chunk':
                setSummary(data.text || '');
                setPhase('summarizing');
                break;
              case 'done':
                setPhase('done');
                es.close();
                break;
              case 'error':
                setError(data.error || 'Unknown error');
                setPhase('error');
                es.close();
                break;
            }
          } catch {}
        };

        es.onerror = () => {
          // Ignore errors, polling will retry
        };

        // Close after 2 seconds to avoid multiple connections
        setTimeout(() => es.close(), 2000);
      } catch {}
    }, 500);
  }, []);

  const handleFileSelected = useCallback(async (file: File) => {
    setFileName(file.name);
    setPhase('converting');
    setTranscript('');
    setPolished('');
    setSummary('');
    setError('');
    lastStateRef.current = '';

    try {
      const formData = new FormData();
      formData.append('file', file);

      const res = await fetch('/api/transcribe', { method: 'POST', body: formData });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || '上传失败');
      }

      const { taskId } = await res.json();
      connectAndPoll(taskId);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase('error');
    }
  }, [connectAndPoll]);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  const isProcessing = phase !== 'idle' && phase !== 'done' && phase !== 'error';
  const hasResult = transcript || polished || summary;

  return (
    <main style={{ minHeight: '100vh', background: '#0f1419', color: '#e7e9ea', padding: '32px 16px' }}>
      <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
        {/* Header */}
        <div style={{ textAlign: 'center', marginBottom: '40px' }}>
          <h1 style={{ fontSize: '28px', fontWeight: '700', color: '#1d9bf0', marginBottom: '8px' }}>
            🎙️ MP4 转文字
          </h1>
          <p style={{ fontSize: '15px', color: '#71767b' }}>
            上传视频 → 自动转写 → AI 润色 → 智能摘要
          </p>
        </div>

        {/* StepBar */}
        <div style={{ maxWidth: '600px', margin: '0 auto 32px' }}>
          <StepBar currentStep={currentStep} labels={STEP_LABELS} />
        </div>

        {/* Progress */}
        {isProcessing && (
          <div style={{ maxWidth: '600px', margin: '0 auto 24px' }}>
            <ProgressBar phase={PHASE_LABELS[phase]} progress={PHASE_PROGRESS[phase]} />
          </div>
        )}

        {/* Upload zone */}
        {phase === 'idle' && (
          <div style={{ maxWidth: '600px', margin: '0 auto' }}>
            <UploadZone onFileSelected={handleFileSelected} disabled={false} />
          </div>
        )}

        {/* Error */}
        {phase === 'error' && (
          <div style={{
            maxWidth: '600px', margin: '0 auto',
            background: '#1c1f23', border: '1px solid #3d1f1f',
            borderRadius: '16px', padding: '24px', textAlign: 'center',
          }}>
            <div style={{ fontSize: '48px', marginBottom: '12px' }}>❌</div>
            <div style={{ color: '#f4212e', marginBottom: '8px', fontSize: '15px' }}>处理失败</div>
            <div style={{ color: '#71767b', fontSize: '13px' }}>{error}</div>
          </div>
        )}

        {/* Results area */}
        {hasResult && phase !== 'idle' && (
          <div>
            {/* Top row: transcript + polished */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: '16px',
              marginBottom: '16px',
            }}>
              <TranscriptPanel text={transcript} fileName={fileName} />
              <PolishPanel text={polished} />
            </div>
            {/* Bottom row: summary */}
            <SummaryPanel text={summary} />
          </div>
        )}

        {/* Done state - show restart button */}
        {phase === 'done' && (
          <div style={{ textAlign: 'center', marginTop: '24px' }}>
            <button
              onClick={() => { setPhase('idle'); setTranscript(''); setPolished(''); setSummary(''); }}
              style={{
                background: '#1d9bf0', color: '#fff', border: 'none',
                borderRadius: '8px', padding: '10px 24px', fontSize: '14px',
                cursor: 'pointer',
              }}
            >
              🔄 再次上传
            </button>
          </div>
        )}
      </div>
    </main>
  );
}