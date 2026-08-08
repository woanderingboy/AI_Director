"""小说创作模块 API - 剧情大纲与关键节点"""
from flask import Blueprint, request, jsonify
from web.models.database import db
from web.models.novel_models import PlotOutline, PlotPoint, WorldSetting, NovelCharacter, bump_novel_version

bp = Blueprint("novel_outline", __name__)


@bp.route("/<int:project_id>/outline", methods=["GET"])
def get_outline(project_id):
    outline = PlotOutline.query.filter_by(project_id=project_id).first()
    if not outline:
        return jsonify(None)
    return jsonify(outline.to_dict())


@bp.route("/<int:project_id>/outline", methods=["POST"])
def save_outline(project_id):
    data = request.get_json()
    outline = PlotOutline.query.filter_by(project_id=project_id).first()
    if not outline:
        outline = PlotOutline(project_id=project_id)
        db.session.add(outline)

    for field in ["title", "genre", "theme", "logline", "synopsis", "conflict", "ending", "ai_context"]:
        if field in data:
            setattr(outline, field, data[field])

    db.session.commit()
    return jsonify(outline.to_dict())


@bp.route("/<int:project_id>/outline/generate", methods=["POST"])
def generate_outline(project_id):
    """AI 生成剧情大纲"""
    data = request.get_json() or {}
    user_hint = data.get("hint", "")

    world = WorldSetting.query.filter_by(project_id=project_id).first()
    chars = NovelCharacter.query.filter_by(project_id=project_id).all()

    world_ctx = ""
    if world:
        world_ctx = world.ai_context or f"{world.name}：{world.world_type}，{world.era}，{world.geography}，{world.power_system}"

    chars_ctx = ""
    if chars:
        chars_ctx = "\n".join([f"- {c.name}（{c.role}）：{c.personality}，{c.background}" for c in chars])

    from web.services.novel_ai_service import generate_outline as ai_gen
    result = ai_gen(world_ctx, chars_ctx, user_hint, project_id=project_id)
    return jsonify({"result": result})


@bp.route("/<int:project_id>/plot-points", methods=["GET"])
def list_plot_points(project_id):
    outline = PlotOutline.query.filter_by(project_id=project_id).first()
    if not outline:
        return jsonify([])
    points = PlotPoint.query.filter_by(outline_id=outline.id).order_by(PlotPoint.sequence).all()
    return jsonify([p.to_dict() for p in points])


@bp.route("/<int:project_id>/plot-points", methods=["POST"])
def create_plot_point(project_id):
    data = request.get_json()
    outline = PlotOutline.query.filter_by(project_id=project_id).first()
    if not outline:
        return jsonify({"error": "请先创建大纲"}), 400

    point = PlotPoint(
        outline_id=outline.id,
        project_id=project_id,
        title=data.get("title", ""),
        point_type=data.get("point_type", "剧情点"),
        sequence=data.get("sequence", 0),
        description=data.get("description", ""),
        characters_involved=data.get("characters_involved", ""),
        emotional_beat=data.get("emotional_beat", ""),
        consequences=data.get("consequences", ""),
        notes=data.get("notes", ""),
    )
    db.session.add(point)
    db.session.commit()
    bump_novel_version(project_id)
    return jsonify(point.to_dict()), 201


@bp.route("/plot-points/<int:point_id>", methods=["PUT"])
def update_plot_point(point_id):
    point = PlotPoint.query.get_or_404(point_id)
    data = request.get_json()
    for field in ["title", "point_type", "sequence", "description",
                  "characters_involved", "emotional_beat", "consequences", "notes"]:
        if field in data:
            setattr(point, field, data[field])
    db.session.commit()
    bump_novel_version(point.project_id)
    return jsonify(point.to_dict())


@bp.route("/plot-points/<int:point_id>", methods=["DELETE"])
def delete_plot_point(point_id):
    point = PlotPoint.query.get_or_404(point_id)
    pid = point.project_id
    db.session.delete(point)
    db.session.commit()
    bump_novel_version(pid)
    return jsonify({"ok": True})


@bp.route("/<int:project_id>/plot-points/generate", methods=["POST"])
def generate_plot_points(project_id):
    """AI 生成关键节点"""
    outline = PlotOutline.query.filter_by(project_id=project_id).first()
    if not outline:
        return jsonify({"error": "请先创建大纲"}), 400

    world = WorldSetting.query.filter_by(project_id=project_id).first()
    chars = NovelCharacter.query.filter_by(project_id=project_id).all()

    world_ctx = world.ai_context or "" if world else ""
    chars_ctx = "\n".join([f"- {c.name}（{c.role}）：{c.personality}" for c in chars]) if chars else ""
    outline_ctx = outline.ai_context or f"{outline.title}：{outline.synopsis}"

    from web.services.novel_ai_service import generate_plot_points as ai_gen
    result = ai_gen(outline_ctx, world_ctx, chars_ctx, project_id=project_id)

    # 自动保存生成的节点
    if isinstance(result, dict) and "points" in result:
        outline_obj = PlotOutline.query.filter_by(project_id=project_id).first()
        for i, pt in enumerate(result["points"]):
            point = PlotPoint(
                outline_id=outline_obj.id,
                project_id=project_id,
                title=pt.get("title", f"节点{i+1}"),
                point_type=pt.get("point_type", "剧情点"),
                sequence=i + 1,
                description=pt.get("description", ""),
                characters_involved=pt.get("characters_involved", ""),
                emotional_beat=pt.get("emotional_beat", ""),
                consequences=pt.get("consequences", ""),
            )
            db.session.add(point)
        db.session.commit()

    return jsonify({"result": result})
