"""MP4 history / reference API.

维护前请先看:
- `F:\\dev-repo\\mp4-to-word-new\\design\\backend\\index.md`
- `F:\\dev-repo\\mp4-to-word-new\\design\\backend\\mp4-history-reference-flow.md`

这里负责把实时任务导出到 reference 历史索引，并提供列表、详情、删除、Ask AI。
"""
from flask import Blueprint, jsonify, request

from backend.services.mp4_history_service import (
    add_mp4_history_qa,
    delete_reference_history_item,
    export_task_to_reference,
    load_reference_history_detail,
    load_reference_history_list,
    reorder_reference_history_items,
)


def create_mp4_history_bp(get_task_by_id, get_polisher):
    mp4_history_bp = Blueprint('mp4_history', __name__)

    @mp4_history_bp.route('/api/reference/mp4-history', methods=['POST'])
    def save_mp4_history():
        data = request.get_json() or {}
        task_id = data.get('task_id')
        if not task_id:
            return jsonify({'error': 'Task ID is required'}), 400

        try:
            task = get_task_by_id(task_id)
            result = export_task_to_reference(task_id, task)
            return jsonify(result)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            return jsonify({'error': f'保存历史记录失败: {exc}'}), 500

    @mp4_history_bp.route('/api/reference/mp4-history')
    def list_mp4_history():
        return jsonify({'items': load_reference_history_list()})

    @mp4_history_bp.route('/api/reference/mp4-history/reorder', methods=['POST'])
    def reorder_mp4_history():
        data = request.get_json() or {}
        ordered_ids = data.get('ordered_ids') or []
        if not isinstance(ordered_ids, list):
            return jsonify({'error': 'ordered_ids must be a list'}), 400
        items = reorder_reference_history_items([str(item_id) for item_id in ordered_ids])
        return jsonify({'items': items})

    @mp4_history_bp.route('/api/reference/mp4-history/<history_id>')
    def get_mp4_history(history_id):
        detail = load_reference_history_detail(history_id)
        if not detail:
            return jsonify({'error': 'History record not found'}), 404
        return jsonify(detail)

    @mp4_history_bp.route('/api/reference/mp4-history/<history_id>', methods=['DELETE'])
    def delete_mp4_history(history_id):
        try:
            deleted = delete_reference_history_item(history_id)
            return jsonify({'id': deleted.get('id'), 'title': deleted.get('title')})
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 404
        except Exception as exc:
            return jsonify({'error': f'删除历史记录失败: {exc}'}), 500

    @mp4_history_bp.route('/api/reference/mp4-history/<history_id>/ask', methods=['POST'])
    def ask_mp4_history(history_id):
        detail = load_reference_history_detail(history_id)
        if not detail:
            return jsonify({'error': 'History record not found'}), 404

        data = request.get_json() or {}
        question = str(data.get('question', '')).strip()
        if not question:
            return jsonify({'error': 'Question cannot be empty'}), 400

        task = detail.get('task') or {}
        polished = str(task.get('polished') or '').strip()
        summary = str(task.get('summary') or '').strip()
        if not polished and not summary:
            return jsonify({'error': 'No content available for Q&A'}), 400

        polisher = get_polisher()
        answer = polisher.ask_about_content(question, polished, summary)
        qa_item = add_mp4_history_qa(history_id, question, answer)
        return jsonify({'item': qa_item})

    return mp4_history_bp
