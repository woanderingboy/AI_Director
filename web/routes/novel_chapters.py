"""小说创作模块 API - 章节与场景"""
from flask import Blueprint, request, jsonify
from web.models.database import db
from web.models.novel_models import (
    NovelChapter, NovelScene, PlotOutline, PlotPoint,
    WorldSetting, NovelCharacter, bump_novel_version
)

bp = Blueprint("novel_chapters", __name__)


# ──── 章节 ────

@bp.route("/<int:project_id>/novel-chapters", methods=["GET"])
def list_chapters(project_id):
    chapters = NovelChapter.query.filter_by(project_id=project_id).order_by(NovelChapter.chapter_number).all()
    return jsonify([c.to_dict() for c in chapters])


@bp.route("/<int:project_id>/novel-chapters", methods=["POST"])
def create_chapter(project_id):
    data = request.get_json()
    max_num = db.session.query(db.func.max(NovelChapter.chapter_number)).filter_by(project_id=project_id).scalar() or 0
    chapter = NovelChapter(
        project_id=project_id,
        chapter_number=data.get("chapter_number", max_num + 1),
        title=data.get("title", f"第{max_num + 1}章"),
        summary=data.get("summary", ""),
        content=data.get("content", ""),
        notes=data.get("notes", ""),
    )
    chapter.word_count = len(chapter.content or "")
    db.session.add(chapter)
    db.session.commit()
    return jsonify(chapter.to_dict()), 201


@bp.route("/novel-chapters/<int:ch_id>", methods=["GET"])
def get_chapter(ch_id):
    chapter = NovelChapter.query.get_or_404(ch_id)
    return jsonify(chapter.to_dict())


@bp.route("/novel-chapters/<int:ch_id>", methods=["PUT"])
def update_chapter(ch_id):
    chapter = NovelChapter.query.get_or_404(ch_id)
    data = request.get_json()
    for field in ["title", "summary", "content", "status", "notes", "chapter_number"]:
        if field in data:
            setattr(chapter, field, data[field])
    if "content" in data:
        chapter.word_count = len(data["content"] or "")
    db.session.commit()
    # 小说内容被改动 → 递增项目 novel_version，标记下游产物（剧本/提示词/图/视频）过期
    bump_novel_version(chapter.project_id)
    return jsonify(chapter.to_dict())


@bp.route("/novel-chapters/<int:ch_id>", methods=["DELETE"])
def delete_chapter(ch_id):
    chapter = NovelChapter.query.get_or_404(ch_id)
    db.session.delete(chapter)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/<int:project_id>/novel-chapters/generate-summary", methods=["POST"])
def generate_chapter_summary(project_id):
    """AI 生成章节概要"""
    data = request.get_json()
    chapter_number = data.get("chapter_number", 1)

    world = WorldSetting.query.filter_by(project_id=project_id).first()
    chars = NovelCharacter.query.filter_by(project_id=project_id).all()
    outline = PlotOutline.query.filter_by(project_id=project_id).first()
    points = []
    if outline:
        points = PlotPoint.query.filter_by(outline_id=outline.id).order_by(PlotPoint.sequence).all()

    world_ctx = world.ai_context or "" if world else ""
    chars_ctx = "\n".join([f"- {c.name}（{c.role}）：{c.personality}" for c in chars]) if chars else ""
    points_ctx = "\n".join([f"{p.sequence}. [{p.point_type}] {p.title}：{p.description}" for p in points]) if points else ""

    # 获取前一章概要
    prev_ch = NovelChapter.query.filter_by(project_id=project_id).filter(
        NovelChapter.chapter_number < chapter_number
    ).order_by(NovelChapter.chapter_number.desc()).first()
    prev_summary = prev_ch.summary if prev_ch else ""

    from web.services.novel_ai_service import generate_chapter_summary as ai_gen
    result = ai_gen(chapter_number, points_ctx, world_ctx, chars_ctx, prev_summary, project_id=project_id)
    return jsonify({"result": result})


# ──── 场景 ────

@bp.route("/novel-chapters/<int:ch_id>/scenes", methods=["GET"])
def list_scenes(ch_id):
    scenes = NovelScene.query.filter_by(chapter_id=ch_id).order_by(NovelScene.scene_number).all()
    return jsonify([s.to_dict() for s in scenes])


@bp.route("/novel-chapters/<int:ch_id>/scenes", methods=["POST"])
def create_scene(ch_id):
    chapter = NovelChapter.query.get_or_404(ch_id)
    data = request.get_json()
    max_num = db.session.query(db.func.max(NovelScene.scene_number)).filter_by(chapter_id=ch_id).scalar() or 0
    scene = NovelScene(
        chapter_id=ch_id,
        project_id=chapter.project_id,
        scene_number=data.get("scene_number", max_num + 1),
        title=data.get("title", f"场景{max_num + 1}"),
        location=data.get("location", ""),
        time_desc=data.get("time_desc", ""),
        characters=data.get("characters", ""),
        summary=data.get("summary", ""),
        content=data.get("content", ""),
        mood=data.get("mood", ""),
        notes=data.get("notes", ""),
    )
    db.session.add(scene)
    db.session.commit()
    return jsonify(scene.to_dict()), 201


@bp.route("/scenes/<int:scene_id>", methods=["PUT"])
def update_scene(scene_id):
    scene = NovelScene.query.get_or_404(scene_id)
    data = request.get_json()
    for field in ["title", "location", "time_desc", "characters", "summary", "content", "mood", "notes", "scene_number"]:
        if field in data:
            setattr(scene, field, data[field])
    db.session.commit()
    # 场景也属于小说内容，改动后同样标记下游过期
    bump_novel_version(scene.project_id)
    return jsonify(scene.to_dict())


@bp.route("/scenes/<int:scene_id>", methods=["DELETE"])
def delete_scene(scene_id):
    scene = NovelScene.query.get_or_404(scene_id)
    db.session.delete(scene)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/scenes/<int:scene_id>/generate-content", methods=["POST"])
def generate_scene_content(scene_id):
    """AI 生成场景正文"""
    scene = NovelScene.query.get_or_404(scene_id)
    chapter = NovelChapter.query.get(scene.chapter_id)

    world = WorldSetting.query.filter_by(project_id=scene.project_id).first()
    chars = NovelCharacter.query.filter_by(project_id=scene.project_id).all()

    world_ctx = world.ai_context or "" if world else ""
    chars_ctx = "\n".join([f"- {c.name}（{c.role}）：{c.appearance}，{c.personality}" for c in chars]) if chars else ""
    chapter_ctx = chapter.summary or chapter.title if chapter else ""
    scene_info = f"地点：{scene.location}，时间：{scene.time_desc}，出场角色：{scene.characters}，概要：{scene.summary}，氛围：{scene.mood}"

    from web.services.novel_ai_service import generate_scene_content as ai_gen
    result = ai_gen(scene_info, chapter_ctx, chars_ctx, world_ctx, project_id=scene.project_id)
    return jsonify({"result": result})


@bp.route("/scenes/<int:scene_id>/polish", methods=["POST"])
def polish_scene(scene_id):
    """AI 润色场景"""
    scene = NovelScene.query.get_or_404(scene_id)
    data = request.get_json()
    instruction = data.get("instruction", "")
    content = data.get("content") or scene.content

    from web.services.novel_ai_service import polish_content
    result = polish_content(content, instruction, project_id=scene.project_id)
    return jsonify({"result": result})
