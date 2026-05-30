from flask import Blueprint, render_template, send_from_directory


def create_public_bp(upload_folder, output_folder):
    public_bp = Blueprint('public', __name__)

    @public_bp.route('/')
    def index():
        return render_template('index.html')

    @public_bp.route('/uploads/<path:filename>')
    def uploaded_file(filename):
        return send_from_directory(upload_folder, filename)

    @public_bp.route('/outputs/<path:filename>')
    def output_file(filename):
        return send_from_directory(output_folder, filename)

    return public_bp
