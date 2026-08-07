"""项目 CRUD API"""
from flask import Blueprint, request, jsonify
from web.models.database import db, ProjectModel
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
