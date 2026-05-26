import sys
sys.path.insert(0, r'F:\dev-repo\mp4-to-word')
from transcribe import Transcriber

print("Loading model...")
t = Transcriber()
print("Model loaded OK")

wav = r'F:\dev-repo\mp4-to-word\uploads\5765768f-ac1f-486b-b4e0-9305905abd9c_audio.wav'
print(f"Testing transcription on {wav}")
r = t._transcribe_segment(wav)
print(f"Result: {repr(r[:100]) if r else 'EMPTY'}")
