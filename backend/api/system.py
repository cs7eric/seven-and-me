from flask import Blueprint, jsonify

from backend.services.db_health_service import check_db_health


def create_system_bp(is_api_configured, is_model_loaded):
    system_bp = Blueprint('system', __name__)

    @system_bp.route('/api/status')
    def status():
        db_health = check_db_health()
        return jsonify({
            'api_configured': bool(is_api_configured()),
            'gpu_available': False,
            'model_loaded': bool(is_model_loaded()),
            'status': 'running',
            'database': db_health,
        })

    @system_bp.route('/api/system/db-health')
    def db_health():
        return jsonify(check_db_health())

    return system_bp
