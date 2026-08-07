"""小说创作模块 API - 角色管理"""
from flask import Blueprint, request, jsonify
from web.models.database import db
from web.models.novel_models import NovelCharacter, WorldSetting

bp = Blueprint("novel_characters", __name__)


@bp.route("/<int:project_id>/characters", methods=["GET"])
def list_characters(project_id):
    chars = NovelCharacter.query.filter_by(project_id=project_id).order_by(NovelCharacter.role.desc()).all()
    return jsonify([c.to_dict() for c in chars])


@bp.route("/<int:project_id>/characters", methods=["POST"])
def create_character(project_id):
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "角色名不能为空"}), 400

    # 自动关联世界观
    world = WorldSetting.query.filter_by(project_id=project_id).first()
    char = NovelCharacter(
        project_id=project_id,
        world_id=world.id if world else 0,
        name=name,
        role=data.get("role", "配角"),
        gender=data.get("gender", ""),
        age=data.get("age", ""),
        appearance=data.get("appearance", ""),
        personality=data.get("personality", ""),
        background=data.get("background", ""),
        ability=data.get("ability", ""),
        motivation=data.get("motivation", ""),
        relationships=data.get("relationships", ""),
        arc=data.get("arc", ""),
        key_quotes=data.get("key_quotes", ""),
        visual_prompt=data.get("visual_prompt", ""),
        notes=data.get("notes", ""),
    )
    db.session.add(char)
    db.session.commit()
    return jsonify(char.to_dict()), 201


@bp.route("/characters/<int:char_id>", methods=["GET"])
def get_character(char_id):
    char = NovelCharacter.query.get_or_404(char_id)
    return jsonify(char.to_dict())


@bp.route("/characters/<int:char_id>", methods=["PUT"])
def update_character(char_id):
    char = NovelCharacter.query.get_or_404(char_id)
    data = request.get_json()
    for field in ["name", "role", "gender", "age", "appearance", "personality",
                  "background", "ability", "motivation", "relationships",
                  "arc", "key_quotes", "visual_prompt", "notes"]:
        if field in data:
            setattr(char, field, data[field])
    db.session.commit()
    return jsonify(char.to_dict())


@bp.route("/characters/<int:char_id>", methods=["DELETE"])
def delete_character(char_id):
    char = NovelCharacter.query.get_or_404(char_id)
    db.session.delete(char)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/<int:project_id>/characters/expand", methods=["POST"])
def expand_character(project_id):
    """AI 扩展角色设定"""
    data = request.get_json()
    char_input = data.get("input", "")
    if not char_input:
        return jsonify({"error": "请输入角色描述"}), 400

    # 获取世界观上下文
    world = WorldSetting.query.filter_by(project_id=project_id).first()
    world_context = world.ai_context or world.notes or "" if world else ""

    from web.services.novel_ai_service import expand_character as ai_expand
    result = ai_expand(char_input, world_context=world_context, project_id=project_id)
    return jsonify({"result": result})
