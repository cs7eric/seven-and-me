import logging

from flask import Flask

from backend.api.mp4_history import create_mp4_history_bp
from backend.api.public import create_public_bp
from backend.api.scheduler import scheduler_bp
from backend.api.self_selected import self_selected_bp
from backend.api.stock.f10 import f10_bp
from backend.api.stock_chart import stock_chart_bp
from backend.api.system import create_system_bp
from backend.api.transcription import create_transcription_bp
from backend.config.settings import API_KEY, GROUP_ID, OUTPUT_FOLDER, UPLOAD_FOLDER
from backend.services.ai_provider_service import ai_provider_registry
from backend.services.scheduler.auction_analysis_scheduler import (
    is_auction_analysis_scheduler_enabled,
    start_auction_analysis_scheduler,
)
from backend.services.scheduler.turnover_scheduler import is_turnover_scheduler_enabled, start_turnover_scheduler
from backend.services.scheduler.stock_universe_scheduler import (
    is_stock_universe_scheduler_enabled,
    start_stock_universe_scheduler,
)
from backend.services.scheduler.market_pulse_scheduler import (
    is_market_pulse_scheduler_enabled,
    start_market_pulse_scheduler,
)
from backend.services.scheduler.market_overview_scheduler import (
    is_market_overview_scheduler_enabled,
    start_market_overview_scheduler,
)
from backend.services.scheduler.daily_eod_incremental_scheduler import (
    is_daily_eod_incremental_scheduler_enabled,
    start_daily_eod_incremental_scheduler,
)
from backend.services.scheduler.ths_industry_constituents_scheduler import (
    is_ths_industry_constituents_scheduler_enabled,
    start_ths_industry_constituents_scheduler,
)
from backend.services.scheduler.market_sentiment_chain_scheduler import (
    is_market_sentiment_chain_scheduler_enabled,
    start_market_sentiment_chain_scheduler,
)
from backend.services.scheduler.ths_industry_constituents_daily_scheduler import (
    is_ths_industry_constituents_daily_scheduler_enabled,
    start_ths_industry_constituents_daily_scheduler,
)
from backend.services.stock.application_analysis_scheduler import (
    is_application_analysis_scheduler_enabled,
    start_application_analysis_scheduler,
)
from backend.services.stock.f10 import get_fundamentals_service
from backend.services.task_runtime_service import runtime_store


logger = logging.getLogger(__name__)


def is_api_configured() -> bool:
    return bool(API_KEY and GROUP_ID)


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(stock_chart_bp)
    app.register_blueprint(f10_bp)
    # 触发 F10 适配器单例构建（懒加载预热）
    get_fundamentals_service()
    app.register_blueprint(create_mp4_history_bp(runtime_store.get_task, ai_provider_registry.get_polisher))
    app.register_blueprint(create_transcription_bp(runtime_store, ai_provider_registry.get_transcriber, ai_provider_registry.get_polisher))
    app.register_blueprint(create_public_bp(UPLOAD_FOLDER, OUTPUT_FOLDER))
    app.register_blueprint(create_system_bp(is_api_configured, ai_provider_registry.is_model_loaded))
    app.register_blueprint(scheduler_bp)
    app.register_blueprint(self_selected_bp)
    if is_application_analysis_scheduler_enabled():
        try:
            start_application_analysis_scheduler()
        except Exception as exc:
            logger.exception('Application Analysis scheduler start failed: %s', exc)
    if is_turnover_scheduler_enabled():
        try:
            start_turnover_scheduler()
        except Exception as exc:
            logger.exception('Turnover scheduler start failed: %s', exc)
    if is_auction_analysis_scheduler_enabled():
        try:
            start_auction_analysis_scheduler()
        except Exception as exc:
            logger.exception('Auction Analysis scheduler start failed: %s', exc)
    if is_stock_universe_scheduler_enabled():
        try:
            start_stock_universe_scheduler()
        except Exception as exc:
            logger.exception('Stock Universe scheduler start failed: %s', exc)
    if is_market_pulse_scheduler_enabled():
        try:
            start_market_pulse_scheduler()
        except Exception as exc:
            logger.exception('Market Pulse scheduler start failed: %s', exc)
    if is_market_overview_scheduler_enabled():
        try:
            start_market_overview_scheduler()
        except Exception as exc:
            logger.exception('Market Overview scheduler start failed: %s', exc)
    if is_ths_industry_constituents_scheduler_enabled():
        try:
            start_ths_industry_constituents_scheduler()
        except Exception as exc:
            logger.exception('THS Industry Constituents scheduler start failed: %s', exc)
    if is_ths_industry_constituents_daily_scheduler_enabled():
        try:
            start_ths_industry_constituents_daily_scheduler()
        except Exception as exc:
            logger.exception('THS Industry Constituents Daily scheduler start failed: %s', exc)
    if is_daily_eod_incremental_scheduler_enabled():
        try:
            start_daily_eod_incremental_scheduler()
        except Exception as exc:
            logger.exception('Daily EOD Incremental scheduler start failed: %s', exc)
    # Market Sentiment component jobs stay manual-only; automatic scheduling is centralized
    # in market_sentiment_chain_scheduler to avoid DuckDB/file lock overlap.
    if is_market_sentiment_chain_scheduler_enabled():
        try:
            start_market_sentiment_chain_scheduler()
        except Exception as exc:
            logger.exception('Market Sentiment Chain scheduler start failed: %s', exc)
