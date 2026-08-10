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


@bp.route("/<int:project_id>/derive-settings", methods=["POST"])
def derive_settings(project_id):
    """从已导入/上传的小说正文，自动推导 世界观 + 主要角色 + 故事梗概（仅预览，不写库）。

    前端拿到预览后可让用户确认「同步」写入。正文取自该项目已导入的 novel_chapters。
    """
    from web.models.novel_models import NovelChapter
    chapters = NovelChapter.query.filter_by(project_id=project_id).order_by(NovelChapter.chapter_number).all()
    if not chapters:
        return jsonify({"ok": False, "error": "该项目还没有任何小说章节，请先导入/上传小说文本"}), 400
    novel_text = "\n\n".join([f"【{c.title}】\n{c.content or ''}" for c in chapters if (c.content or '').strip()])
    if not novel_text.strip():
        return jsonify({"ok": False, "error": "章节正文为空，无法推导"}), 400

    from web.services.novel_ai_service import derive_settings_from_novel
    try:
        result = derive_settings_from_novel(novel_text, project_id=project_id)
    except Exception as e:
        return jsonify({"ok": False, "error": f"推导失败：{e}"}), 500
    return jsonify({"ok": True, "data": result})


@bp.route("/<int:project_id>/sync-settings", methods=["POST"])
def sync_settings(project_id):
    """将 derive-settings 的预览结果写入库。

    规则（安全、不覆盖已有）：
    - 世界观：已存在则只补齐空字段；不存在则新建。
    - 角色：只新增预览中有、而库内无同名者；已有同名角色不改动。
    - 大纲：已有则不改；没有则新建。
    """
    data = request.get_json() or {}
    payload = data.get("data") or {}
    world_in = payload.get("world") or {}
    chars_in = payload.get("characters") or []
    outline_in = payload.get("outline") or {}

    from web.models.novel_models import NovelCharacter, PlotOutline

    # 1) 世界观：补齐空字段
    world = WorldSetting.query.filter_by(project_id=project_id).first()
    world_created = False
    if not world:
        world = WorldSetting(project_id=project_id)
        db.session.add(world)
        world_created = True
    for f in ["name", "world_type", "era", "geography", "power_system",
              "social_structure", "history", "rules", "culture", "ai_context"]:
        v = (world_in.get(f) or "").strip()
        if v and not (getattr(world, f) or "").strip():
            setattr(world, f, v)
    db.session.flush()

    # 2) 角色：只新增无同名者
    existing_names = {c.name for c in NovelCharacter.query.filter_by(project_id=project_id).all()}
    added_chars = []
    for c in chars_in:
        name = (c.get("name") or "").strip()
        if not name or name in existing_names:
            continue
        char = NovelCharacter(
            project_id=project_id,
            world_id=world.id,
            name=name,
            role=(c.get("role") or "配角").strip(),
            gender=(c.get("gender") or "").strip(),
            age=(c.get("age") or "").strip(),
            appearance=(c.get("appearance") or "").strip(),
            personality=(c.get("personality") or "").strip(),
            background=(c.get("background") or "").strip(),
            ability=(c.get("ability") or "").strip(),
            motivation=(c.get("motivation") or "").strip(),
            relationships=(c.get("relationships") or "").strip(),
            visual_prompt=(c.get("visual_prompt") or "").strip(),
        )
        db.session.add(char)
        added_chars.append(name)
        existing_names.add(name)

    # 3) 大纲：没有才新建
    outline = PlotOutline.query.filter_by(project_id=project_id).first()
    outline_created = False
    if not outline:
        outline = PlotOutline(project_id=project_id)
        db.session.add(outline)
        outline_created = True
    for f in ["logline", "theme", "synopsis", "conflict", "ending"]:
        v = (outline_in.get(f) or "").strip()
        if v and not (getattr(outline, f) or "").strip():
            setattr(outline, f, v)

    db.session.commit()
    return jsonify({
        "ok": True,
        "world_created": world_created,
        "characters_added": added_chars,
        "outline_created": outline_created,
    })
