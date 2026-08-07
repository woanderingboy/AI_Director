"""小说创作模块 API - 世界观设定"""
from flask import Blueprint, request, jsonify
from web.models.database import db
from web.models.novel_models import WorldSetting

bp = Blueprint("novel_world", __name__)


@bp.route("/<int:project_id>/world", methods=["GET"])
def get_world(project_id):
    world = WorldSetting.query.filter_by(project_id=project_id).first()
    if not world:
        return jsonify(None)
    return jsonify(world.to_dict())


@bp.route("/<int:project_id>/world", methods=["POST"])
def save_world(project_id):
    data = request.get_json()
    world = WorldSetting.query.filter_by(project_id=project_id).first()
    if not world:
        world = WorldSetting(project_id=project_id)
        db.session.add(world)

    for field in ["name", "world_type", "era", "geography", "power_system",
                  "social_structure", "history", "rules", "culture", "notes", "ai_context"]:
        if field in data:
            setattr(world, field, data[field])

    db.session.commit()
    return jsonify(world.to_dict())


@bp.route("/<int:project_id>/world/expand", methods=["POST"])
def expand_world(project_id):
    """AI 扩展世界观"""
    data = request.get_json()
    user_input = data.get("input", "")
    if not user_input:
        return jsonify({"error": "请输入世界观描述"}), 400

    from web.services.novel_ai_service import expand_world as ai_expand
    result = ai_expand(user_input, project_id=project_id)
    return jsonify({"result": result})
