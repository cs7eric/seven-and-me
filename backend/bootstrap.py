from flask import Flask

from backend.api.mp4_history import create_mp4_history_bp
from backend.api.public import create_public_bp
from backend.api.stock_chart import stock_chart_bp
from backend.api.system import create_system_bp
from backend.api.transcription import create_transcription_bp
from backend.config.settings import API_KEY, GROUP_ID, OUTPUT_FOLDER, UPLOAD_FOLDER
from backend.services.ai_provider_service import ai_provider_registry
from backend.services.stock.application_analysis_scheduler import (
    is_application_analysis_scheduler_enabled,
    start_application_analysis_scheduler,
)
from backend.services.task_runtime_service import runtime_store


def is_api_configured() -> bool:
    return bool(API_KEY and GROUP_ID)


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(stock_chart_bp)
    app.register_blueprint(create_mp4_history_bp(runtime_store.get_task, ai_provider_registry.get_polisher))
    app.register_blueprint(create_transcription_bp(runtime_store, ai_provider_registry.get_transcriber, ai_provider_registry.get_polisher))
    app.register_blueprint(create_public_bp(UPLOAD_FOLDER, OUTPUT_FOLDER))
    app.register_blueprint(create_system_bp(is_api_configured, ai_provider_registry.is_model_loaded))
    if is_application_analysis_scheduler_enabled():
        try:
            start_application_analysis_scheduler()
        except Exception as exc:
            print(f'[Bootstrap] Application Analysis scheduler 启动失败: {exc}', flush=True)
