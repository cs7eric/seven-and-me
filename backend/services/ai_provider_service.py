import sys

from polisher import TextPolisher
from transcribe import Transcriber
from backend.services.ai_adapter_service import AIAdapterRouter

# AI Provider architecture docs:
#   design/backend/ai-provider.md
# Keep that document in sync when changing provider registry entrypoints.


class AIProviderRegistry:
    def __init__(self):
        self._transcriber = None
        self._polisher = None
        self._ai_router = None

    def get_transcriber(self):
        if self._transcriber is None:
            print('[App] 初始化 Whisper 模型')
            sys.stdout.flush()
            self._transcriber = Transcriber()
        return self._transcriber

    def get_polisher(self):
        if self._polisher is None:
            print('[App] 初始化 AI Provider')
            sys.stdout.flush()
            self._polisher = TextPolisher()
        return self._polisher

    def get_ai_router(self):
        if self._ai_router is None:
            self._ai_router = AIAdapterRouter()
        return self._ai_router

    def is_model_loaded(self) -> bool:
        return self._transcriber is not None


ai_provider_registry = AIProviderRegistry()
