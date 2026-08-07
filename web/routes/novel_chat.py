"""小说创作模块 API - 自由对话"""
from flask import Blueprint, request, jsonify
from web.models.database import db
from web.models.novel_models import WorldSetting, NovelCharacter, PlotOutline

bp = Blueprint("novel_chat", __name__)


@bp.route("/<int:project_id>/chat", methods=["POST"])
def chat(project_id):
    """小说创作自由对话"""
    data = request.get_json()
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "请输入内容"}), 400

    # 自动收集项目上下文
    context_parts = []
    world = WorldSetting.query.filter_by(project_id=project_id).first()
    if world:
        context_parts.append(f"世界观：{world.ai_context or world.notes or world.name}")
    chars = NovelCharacter.query.filter_by(project_id=project_id).all()
    if chars:
        context_parts.append("角色：" + "、".join([f"{c.name}({c.role})" for c in chars]))
    outline = PlotOutline.query.filter_by(project_id=project_id).first()
    if outline:
        context_parts.append(f"大纲：{outline.synopsis or outline.logline}")

    context = "\n".join(context_parts)

    from web.services.novel_ai_service import ai_chat_novel
    result = ai_chat_novel(prompt, context, project_id=project_id)
    return jsonify({"result": result})


@bp.route("/<int:project_id>/context-summary", methods=["GET"])
def context_summary(project_id):
    """获取当前项目的完整创作上下文摘要"""
    world = WorldSetting.query.filter_by(project_id=project_id).first()
    chars = NovelCharacter.query.filter_by(project_id=project_id).all()
    outline = PlotOutline.query.filter_by(project_id=project_id).first()

    from web.models.novel_models import PlotPoint, NovelChapter
    points = []
    if outline:
        points = PlotPoint.query.filter_by(outline_id=outline.id).order_by(PlotPoint.sequence).all()
    chapters = NovelChapter.query.filter_by(project_id=project_id).order_by(NovelChapter.chapter_number).all()

    return jsonify({
        "world": world.to_dict() if world else None,
        "characters": [c.to_dict() for c in chars],
        "outline": outline.to_dict() if outline else None,
        "plot_points": [p.to_dict() for p in points],
        "chapters": [c.to_dict() for c in chapters],
    })
