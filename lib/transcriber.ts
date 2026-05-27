import * as fs from 'fs';
import * as path from 'path';
import { spawn } from 'child_process';

// ffmpeg is installed system-wide
function getFFmpegPath(): string {
  return 'ffmpeg';
}

// --- Audio conversion ---
export async function convertVideoToAudio(videoPath: string, outputPath: string): Promise<void> {
  const ffmpegPath = getFFmpegPath();
  const args = ['-y', '-i', videoPath, '-ar', '16000', '-ac', '1', '-acodec', 'pcm_s16le', outputPath];

  return new Promise((resolve, reject) => {
    const proc = spawn(ffmpegPath, args);
    let stderr = '';
    proc.stderr.on('data', (d) => { stderr += d.toString(); });
    proc.on('close', (code) => {
      if (code === 0) resolve();
      else {
        console.error('[FFmpeg error]', stderr);
        reject(new Error(`FFmpeg exited with code ${code}`));
      }
    });
    proc.on('error', reject);
  });
}

// --- Whisper transcription ---
let transformersModule: any = null;
let whisperPipeline: any = null;

async function loadWhisper() {
  if (!whisperPipeline) {
    transformersModule = await import('transformers');
    const modelPath = path.join(process.cwd(), 'models', 'AI-ModelScope', 'whisper-large-v3');
    const device = 'cuda';
    console.log('[Whisper] Loading model from', modelPath, 'device:', device);
    whisperPipeline = await transformersModule.pipeline('automatic-speech-recognition', modelPath, {
      device,
    });
    console.log('[Whisper] Model loaded');
  }
  return whisperPipeline;
}

function parseAudioChunk(audioSamples: Float32Array, sampleRate: number): Float32Array {
  const samples = audioSamples;
  const targetLength = Math.floor(sampleRate * 30);
  if (samples.length > targetLength) {
    return samples.slice(0, targetLength);
  }
  return samples;
}

export async function transcribe_streaming(
  audioPath: string,
  chunkDuration = 30,
  callbacks: {
    onChunk: (idx: number, text: string, isFinal: boolean) => void;
  }
): Promise<string> {
  const pipeline = await loadWhisper();

  let audio: Float32Array;
  let sampleRate = 16000;

  try {
    const ta = await import('torchaudio');
    const [waveform, sr] = await ta.load(audioPath);
    sampleRate = sr;
    audio = waveform.flatten().to('cpu').tolist() as unknown as Float32Array;
  } catch {
    try {
      const sf = await import('soundfile');
      const [data, sr] = sf.read(audioPath, { dtype: 'float32' }) as [any, number];
      sampleRate = sr;
      audio = Float32Array.from(data.flatten ? data.flatten() : data);
    } catch {
      const scipy = await import('scipy.signal');
      const sfModule = await import('soundfile');
      const [data, sr] = sfModule.read(audioPath) as [any, number];
      sampleRate = sr;
      const floatData = new Float32Array(data.length);
      for (let i = 0; i < data.length; i++) floatData[i] = data[i];
      const targetLen = 16000 * 30;
      if (floatData.length > targetLen) {
        audio = scipy.resample(floatData, targetLen);
      } else {
        audio = floatData;
      }
    }
  }

  const durationSec = audio.length / sampleRate;
  const totalChunks = Math.ceil(durationSec / chunkDuration);
  let fullTranscript = '';

  for (let i = 0; i < totalChunks; i++) {
    const start = i * sampleRate * chunkDuration;
    const end = Math.min(start + sampleRate * chunkDuration, audio.length);
    const chunk = audio.slice(start, end);
    const isFinal = i === totalChunks - 1;

    const chunkTensor = new (transformersModule as any).Tensor('float32', Array.from(chunk));

    const result = await whisperPipeline({
      input_features: chunkTensor,
      generate_kwargs: {
        language: 'zh',
        task: 'transcribe',
        timestamp_granularities: ['chunk'],
      },
    });

    const text = result?.text?.trim() || '';
    if (text) {
      fullTranscript += (fullTranscript ? ' ' : '') + text;
      callbacks.onChunk(i, fullTranscript, isFinal);
    }

    // Free tensor
    chunkTensor.dispose();
  }

  return fullTranscript;
}

export async function getAudioDuration(audioPath: string): Promise<number> {
  const ffmpegPath = getFFmpegPath();
  return new Promise((resolve, reject) => {
    const proc = spawn(ffmpegPath, ['-i', audioPath, '-f', 'null', '-']);
    const stderr: Buffer[] = [];
    proc.stderr.on('data', (d) => stderr.push(d));
    proc.on('close', () => {
      const out = Buffer.concat(stderr).toString();
      const m = out.match(/Duration: (\d+):(\d+):(\d+\.\d+)/);
      if (m) {
        const h = parseInt(m[1]), min = parseInt(m[2]), s = parseFloat(m[3]);
        resolve(h * 3600 + min * 60 + s);
      } else {
        resolve(0);
      }
    });
    proc.on('error', reject);
  });
}