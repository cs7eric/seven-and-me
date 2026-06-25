from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS

from backend.bootstrap import register_blueprints
from backend.config.settings import ensure_app_directories
from backend.logging_config import configure_logging, init_request_logging


def create_app(*, start_schedulers: bool = True) -> Flask:
    load_dotenv()
    configure_logging()
    app = Flask(__name__.split('.')[0], static_folder='static')
    CORS(app)
    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024
    ensure_app_directories()
    init_request_logging(app)
    register_blueprints(app, start_schedulers=start_schedulers)
    return app
