from __future__ import annotations

import logging
from logging.config import dictConfig
import os
from pathlib import Path
import sys
import time
import uuid

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException
from backend.config.settings import BASE_DIR


DEFAULT_LOG_FORMAT = (
    '%(asctime)s.%(msecs)03d %(levelname)-8s '
    '[%(process)d:%(threadName)s] %(name)s - %(message)s'
)
DEFAULT_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


def _log_level() -> str:
    return os.getenv('APP_LOG_LEVEL', 'INFO').strip().upper() or 'INFO'


def _log_dir() -> Path:
    path = BASE_DIR / 'logs'
    path.mkdir(parents=True, exist_ok=True)
    return path


def configure_logging() -> None:
    log_file = str(_log_dir() / 'backend.log')
    dictConfig({
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'default': {
                'format': os.getenv('APP_LOG_FORMAT', DEFAULT_LOG_FORMAT),
                'datefmt': os.getenv('APP_LOG_DATE_FORMAT', DEFAULT_DATE_FORMAT),
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'stream': sys.stdout,
                'formatter': 'default',
            },
            'file': {
                'class': 'logging.handlers.TimedRotatingFileHandler',
                'filename': log_file,
                'when': 'midnight',
                'backupCount': 7,
                'encoding': 'utf-8',
                'formatter': 'default',
            },
        },
        'root': {
            'level': _log_level(),
            'handlers': ['console', 'file'],
        },
        'loggers': {
            'werkzeug': {
                'level': os.getenv('WERKZEUG_LOG_LEVEL', 'INFO').strip().upper() or 'INFO',
                'handlers': ['console', 'file'],
                'propagate': False,
            },
        },
    })


def init_request_logging(app: Flask) -> None:
    logger = logging.getLogger('backend.request')

    @app.before_request
    def _start_request_timer() -> None:
        g.request_started_at = time.perf_counter()
        g.request_id = request.headers.get('X-Request-ID') or uuid.uuid4().hex[:12]

    @app.after_request
    def _log_request(response):
        started_at = getattr(g, 'request_started_at', None)
        elapsed_ms = (time.perf_counter() - started_at) * 1000 if started_at else 0.0
        request_id = getattr(g, 'request_id', '-')
        content_length = response.calculate_content_length()
        logger.info(
            'request id=%s method=%s path=%s status=%s elapsed_ms=%.1f remote=%s bytes=%s query=%s',
            request_id,
            request.method,
            request.path,
            response.status_code,
            elapsed_ms,
            request.headers.get('X-Forwarded-For', request.remote_addr),
            content_length if content_length is not None else '-',
            request.query_string.decode('utf-8', errors='replace') or '-',
        )
        response.headers['X-Request-ID'] = request_id
        return response

    @app.errorhandler(Exception)
    def _log_unhandled_exception(exc: Exception):
        request_id = getattr(g, 'request_id', '-')
        if isinstance(exc, HTTPException):
            return exc

        logger.exception(
            'unhandled id=%s method=%s path=%s remote=%s query=%s',
            request_id,
            request.method,
            request.path,
            request.headers.get('X-Forwarded-For', request.remote_addr),
            request.query_string.decode('utf-8', errors='replace') or '-',
        )
        return jsonify({
            'error': 'internal_server_error',
            'message': str(exc),
            'request_id': request_id,
        }), 500
