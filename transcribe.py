import os
import tempfile
import torch
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline
from pathlib import Path
import subprocess
import imageio_ffmpeg
import numpy as np


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
        """转写单个音频文件"""
        return self._transcribe_file(audio_path, language="zh")

    def _load_audio(self, audio_path: str):
        """加载音频文件，返回 (numpy_waveform_1d, sample_rate)"""
        try:
            import torchaudio
            waveform, sr = torchaudio.load(audio_path)
            # shape: [channels, samples], 确保是 [samples]
            if waveform.shape[0] > 1:
                waveform = waveform.mean(dim=0)
            else:
                waveform = waveform.squeeze(0)  # [1, N] -> [N]
            if sr != 16000:
                waveform = torchaudio.functional.resample(waveform, sr, 16000)
                sr = 16000
            return waveform.numpy(), sr
        except Exception as e:
            print(f"[Transcriber] torchaudio 加载失败: {e}")
            try:
                import soundfile as sf
                import scipy.signal
                data, sr = sf.read(audio_path, dtype='float32')
                if len(data.shape) > 1:
                    data = data.mean(axis=1)
                if sr != 16000:
                    num_samples = int(len(data) * 16000 / sr)
                    data = scipy.signal.resample(data, num_samples)
                    sr = 16000
                return data, sr
            except Exception as e2:
                print(f"[Transcriber] soundfile 加载也失败: {e2}")
                return None, None

    def transcribe_streaming(self, audio_path: str, chunk_duration: int = 30, callback=None):
        """
        流式转写：按时间段分片转写，实时回调结果
        callback(chunk_idx, text, is_final)
        """
        print(f"[Transcriber] transcribe_streaming 开始, audio={audio_path}, duration={chunk_duration}s")
        try:
            import torchaudio
            TORCHAUDIO_AVAILABLE = True
        except ImportError:
            TORCHAUDIO_AVAILABLE = False

        if TORCHAUDIO_AVAILABLE:
            try:
                info = torchaudio.info(audio_path)
                duration = info.num_frames / info.sample_rate
            except Exception:
                TORCHAUDIO_AVAILABLE = False
                duration = self._get_audio_duration(audio_path)
        else:
            duration = self._get_audio_duration(audio_path)

        print(f"[Transcriber] 音频总时长: {duration:.1f}s")

        if duration <= 0:
            duration = 300

        # 预加载整个音频
        full_waveform, sr = self._load_audio(audio_path)
        if full_waveform is None:
            print("[Transcriber] 无法加载音频")
            return ""

        total_samples = len(full_waveform)
        chunk_samples = chunk_duration * sr

        print(f"[Transcriber] 总样本={total_samples}, chunk_samples={chunk_samples}, chunks={total_samples // chunk_samples + 1}")

        all_text = []
        chunk_idx = 0

        for start in range(0, total_samples, chunk_samples):
            end = min(start + chunk_samples, total_samples)
            chunk_waveform = full_waveform[start:end]
            chunk_len_s = len(chunk_waveform) / sr
            print(f"[Transcriber] chunk {chunk_idx}: {chunk_len_s:.1f}s ({start}-{end})")

            # 传音频数组，每个chunk最大30秒，不会触发mel>3000问题
            chunk_text = self._transcribe_array(chunk_waveform, sr)
            if chunk_text:
                all_text.append(chunk_text)
                print(f"[Transcriber] chunk {chunk_idx} 完成: {len(chunk_text)} 字")

            is_final = (end >= total_samples)
            if callback:
                callback(chunk_idx, " ".join(all_text), is_final)

            chunk_idx += 1

        return " ".join(all_text)

    def _transcribe_array(self, waveform: np.ndarray, sampling_rate: int, language: str = "zh") -> str:
        """用 feature_extractor 提取特征 + model.generate"""
        try:
            # 直接用 feature_extractor 提取 mel spectrogram
            inputs = self.processor.feature_extractor(
                raw_speech=waveform,
                sampling_rate=sampling_rate,
                return_tensors="pt",
            )
            # 转换到与模型相同的 dtype
            dtype = self.model.dtype
            inputs = {k: v.to(dtype=dtype, device=self.model.device) if hasattr(v, 'to') else v for k, v in inputs.items()}

            # generate
            generated_ids = self.model.generate(
                **inputs,
                return_timestamps=False,
                language=language,
                task="transcribe",
                max_new_tokens=512,
            )

            text = self.processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
            return text.strip()

        except Exception as e:
            print(f"[Transcriber] 转写失败: {e}")
            import traceback
            traceback.print_exc()
            return ""

    def _transcribe_file(self, audio_path: str, language: str = "zh") -> str:
        """转写音频文件"""
        waveform, sr = self._load_audio(audio_path)
        if waveform is None:
            return ""
        return self._transcribe_array(waveform, sr, language)

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
