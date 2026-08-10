"""项目 CRUD API"""
from flask import Blueprint, request, jsonify, current_app
from web.models.database import db, ProjectModel
from web.services.pipeline_service import PipelineService
import os

bp = Blueprint("projects", __name__)


@bp.route("", methods=["GET"])
def list_projects():
    projects = ProjectModel.query.order_by(ProjectModel.updated_time.desc()).all()
    return jsonify([p.to_dict() for p in projects])


@bp.route("", methods=["POST"])
def create_project():
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "项目名称不能为空"}), 400

    if ProjectModel.query.filter_by(name=name).first():
        return jsonify({"error": "项目已存在"}), 400

    project = ProjectModel(
        name=name,
        description=data.get("description", ""),
        genre=data.get("genre", "剧情"),
    )
    db.session.add(project)
    db.session.commit()

    # 创建目录结构
    from flask import current_app
    root_path = current_app.config["ROOT_PATH"]
    from web.services.project_service import ProjectService
    svc = ProjectService(root_path)
    svc.create_project(name)

    return jsonify(project.to_dict()), 201


@bp.route("/<int:project_id>", methods=["GET"])
def get_project(project_id):
    project = ProjectModel.query.get_or_404(project_id)
    return jsonify(project.to_dict())


@bp.route("/<int:project_id>", methods=["PUT"])
def update_project(project_id):
    project = ProjectModel.query.get_or_404(project_id)
    data = request.get_json()
    if "name" in data:
        project.name = data["name"]
    if "description" in data:
        project.description = data["description"]
    if "genre" in data:
        project.genre = data["genre"]
    db.session.commit()
    return jsonify(project.to_dict())


@bp.route("/<int:project_id>", methods=["DELETE"])
def delete_project(project_id):
    project = ProjectModel.query.get_or_404(project_id)
    db.session.delete(project)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/batch-delete", methods=["POST"])
def batch_delete_projects():
    """批量删除项目（仅删除数据库记录，保留 02_Projects 下的项目文件）。

    body: {"ids": [1, 2, 3]}   id 不存在的会被忽略。
    """
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return jsonify({"ok": False, "error": "缺少 ids 列表"}), 400
    ids = [int(x) for x in ids if str(x).isdigit()]
    if not ids:
        return jsonify({"ok": False, "error": "ids 为空或格式非法"}), 400
    deleted = 0
    for pid in ids:
        project = ProjectModel.query.get(pid)
        if project:
            db.session.delete(project)
            deleted += 1
    db.session.commit()
    return jsonify({"ok": True, "deleted": deleted, "requested": len(ids)})


@bp.route("/<int:project_id>/freshness", methods=["GET"])
def project_freshness(project_id):
    """下游产物新鲜度：基于项目 novel_version 与各阶段产物目录的 .novel_version 标记判断。

    返回每个阶段是否存在产物、其基于的小说版本、以及是否过期（版本落后于当前小说）。
    stale=True 表示该阶段产物是基于「旧小说」生成的，上游改动后建议重跑。
    """
    project = ProjectModel.query.get_or_404(project_id)
    cur_version = project.novel_version or 0
    root = current_app.config["ROOT_PATH"]
    proj_dir = os.path.join(root, "02_Projects", project.name)

    stage_dirs = {
        "script": "05_Script",
        "prompt": "07_Prompt",
        "image": "08_Image",
        "video": "09_Video",
    }
    stages = {}
    for key, sub in stage_dirs.items():
        d = os.path.join(proj_dir, sub)
        marked = PipelineService._read_novel_version_marker(d)
        exists = marked is not None and any(
            fn.endswith((".json", ".png", ".jpg", ".mp4"))
            for fn in os.listdir(d)
        ) if os.path.isdir(d) else False
        stages[key] = {
            "exists": bool(exists),
            "version": marked,
            "stale": bool(exists and marked is not None and marked < cur_version),
        }

    stale_count = sum(1 for s in stages.values() if s["stale"])
    return jsonify({
        "project_id": project_id,
        "novel_version": cur_version,
        "stale_count": stale_count,
        "any_stale": stale_count > 0,
        "stages": stages,
    })
