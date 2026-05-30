import sys

from polisher import TextPolisher
from transcribe import Transcriber


class AIProviderRegistry:
    def __init__(self):
        self._transcriber = None
        self._polisher = None

    def get_transcriber(self):
        if self._transcriber is None:
            print('[App] 初始化 Whisper 模型')
            sys.stdout.flush()
            self._transcriber = Transcriber()
        return self._transcriber

    def get_polisher(self):
        if self._polisher is None:
            print('[App] 初始化 MiniMax AI')
            sys.stdout.flush()
            self._polisher = TextPolisher()
        return self._polisher

    def is_model_loaded(self) -> bool:
        return self._transcriber is not None


ai_provider_registry = AIProviderRegistry()
