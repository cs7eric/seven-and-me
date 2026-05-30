from flask import Blueprint, jsonify


def create_system_bp(is_api_configured, is_model_loaded):
    system_bp = Blueprint('system', __name__)

    @system_bp.route('/api/status')
    def status():
        return jsonify({
            'api_configured': bool(is_api_configured()),
            'gpu_available': False,
            'model_loaded': bool(is_model_loaded()),
            'status': 'running',
        })

    return system_bp
