from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS

from backend.bootstrap import register_blueprints
from backend.config.settings import ensure_app_directories


def create_app() -> Flask:
    load_dotenv()
    app = Flask(__name__.split('.')[0], static_folder='static')
    CORS(app)
    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024
    ensure_app_directories()
    register_blueprints(app)
    return app
