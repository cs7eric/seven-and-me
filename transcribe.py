import os
import torch
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline
from pathlib import Path
import subprocess
import imageio_ffmpeg
import math


class Transcriber:
    def __init__(self):
        print("[Transcriber] 初始化 Whisper Large-v3 模型...")
        self.model = None
        self.processor = None
        self.pipe = None
        self._load_model()

    def _load_model(self):
        model_path = Path(__file__).parent / "models" / "AI-ModelScope" / "whisper-large-v3"
        if not model_path.exists():
            raise FileNotFoundError(f"模型路径不存在: {model_path}")

        device = "cuda" if torch.cuda.is_available() else "cpu"
        torch_dtype = torch.float16 if device == "cuda" else torch.float32

        print(f"[Transcriber] 设备: {device}, dtype: {torch_dtype}")

        self.model = AutoModelForSpeechSeq2Seq.from_pretrained(
            str(model_path), torch_dtype=torch_dtype, low_cpu_mem_usage=True, use_safetensors=True
        )
        self.model.to(device)

        self.processor = AutoProcessor.from_pretrained(str(model_path))

        self.pipe = pipeline(
            "automatic-speech-recognition",
            model=self.model,
            tokenizer=self.processor.tokenizer,
            feature_extractor=self.processor.feature_extractor,
            torch_dtype=torch_dtype,
            device=device,
        )
        print("[Transcriber] 模型加载完成")

    def transcribe(self, audio_path: str) -> str:
        """转写单个音频文件（完整转写）"""
        return self._transcribe_segment(audio_path, language="zh")

    def transcribe_streaming(self, audio_path: str, chunk_duration: int = 30, callback=None):
        """
        流式转写：按时间段分片转写，实时回调结果
        callback(chunk_idx, text, is_final)
        """
        try:
            import torchaudio
            TORCHAUDIO_AVAILABLE = True
        except ImportError:
            TORCHAUDIO_AVAILABLE = False
            print("[Transcriber] torchaudio 不可用，使用 ffmpeg 获取时长")

        if TORCHAUDIO_AVAILABLE:
            try:
                info = torchaudio.info(audio_path)
                sample_rate = info.sample_rate
                total_frames = info.num_frames
                duration = total_frames / sample_rate
            except Exception as e:
                print(f"[Transcriber] torchaudio 获取时长失败: {e}, 使用 ffmpeg")
                duration = self._get_audio_duration(audio_path)
                TORCHAUDIO_AVAILABLE = False
        else:
            duration = self._get_audio_duration(audio_path)

        print(f"[Transcriber] 音频总时长: {duration:.1f}s")

        if duration <= 0:
            duration = 300  # 默认 5 分钟

        all_text = []

        for i in range(0, int(duration), chunk_duration):
            start_time = i
            end_time = min(i + chunk_duration, duration)
            chunk_path = f"/tmp/whisper_chunk_{i // chunk_duration}.wav"

            # 提取片段
            ffmpeg_cmd = [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-ss", str(start_time),
                "-t", str(end_time - start_time),
                "-i", audio_path,
                "-ar", "16000",
                "-ac", "1",
                "-acodec", "pcm_s16le",
                chunk_path,
            ]

            try:
                subprocess.run(ffmpeg_cmd, capture_output=True, timeout=60)
            except subprocess.TimeoutExpired:
                print(f"[Transcriber] 提取片段超时")
                continue

            # 转写片段
            chunk_text = self._transcribe_segment(chunk_path)
            if chunk_text:
                all_text.append(chunk_text)

            if callback:
                callback(i // chunk_duration, " ".join(all_text), end_time >= duration)

            # 清理临时文件
            try:
                os.remove(chunk_path)
            except:
                pass

        return " ".join(all_text)

    def _transcribe_segment(self, audio_path: str, language: str = "zh") -> str:
        """转写单个音频片段"""
        try:
            generate_kwargs = {
                "max_new_tokens": 256,
                "language": language,
                "task": "transcribe",
                "condition_on_prev_tokens": False,
                "return_timestamps": True,
            }

            result = self.pipe(audio_path, generate_kwargs=generate_kwargs)

            if isinstance(result, dict) and "text" in result:
                return result["text"].strip()
            return str(result).strip()

        except Exception as e:
            print(f"[Transcriber] 转写片段失败: {e}")
            return ""

    def _get_audio_duration(self, audio_path: str) -> float:
        """获取音频时长"""
        try:
            cmd = [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-i", audio_path,
                "-f", "null", "-"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            import re
            match = re.search(r"Duration: (\d+):(\d+):(\d+)\.(\d+)", result.stderr)
            if match:
                h, m, s, ms = match.groups()
                return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) * 0.01
        except Exception as e:
            print(f"[Transcriber] 获取时长失败: {e}")
        return 0