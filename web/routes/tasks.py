"""任务查询 API"""
from flask import Blueprint, request, jsonify, current_app

bp = Blueprint("tasks", __name__)


@bp.route("", methods=["GET"])
def list_tasks():
    project_id = request.args.get("project_id", type=int)
    limit = request.args.get("limit", 20, type=int)
    tasks = current_app.task_manager.list_tasks(project_id=project_id, limit=limit)
    return jsonify(tasks)


@bp.route("/<task_id>", methods=["GET"])
def get_task(task_id):
    task = current_app.task_manager.get_task(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(task)


@bp.route("/<task_id>/stop", methods=["POST"])
def stop_task(task_id):
    ok = current_app.task_manager.stop_task(task_id)
    return jsonify({"ok": ok})


@bp.route("/clean", methods=["POST"])
def clean_tasks():
    """清理已完成的任务"""
    from web.models.database import db, TaskModel
    deleted = TaskModel.query.filter(TaskModel.status.in_(["success", "fail", "cancelled"])).delete()
    db.session.commit()
    return jsonify({"ok": True, "message": f"已清理 {deleted} 条任务记录"})
