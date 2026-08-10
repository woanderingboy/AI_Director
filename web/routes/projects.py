"""项目 CRUD API"""
from flask import Blueprint, request, jsonify, current_app
from web.models.database import db, ProjectModel
from web.services.pipeline_service import PipelineService
import os

bp = Blueprint("projects", __name__)


@bp.route("/<int:project_id>/scripts", methods=["GET"])
def list_project_scripts(project_id):
    """返回项目的剧本列表（含 script_id、文件名、标题、镜头数），供剧本标签预览与「下一步」使用。"""
    project = ProjectModel.query.get_or_404(project_id)
    from web.models.database import ScriptModel
    # 仅保留属于本项目的剧本：通过 chapter / novel_chapter 关联项目
    from web.models.database import ChapterModel
    from web.models.novel_models import NovelChapter
    result = []
    for sm in ScriptModel.query.all():
        proj_id = None
        if sm.chapter_id:
            ch = ChapterModel.query.get(sm.chapter_id)
            proj_id = ch.project_id if ch else None
        elif sm.novel_chapter_id:
            nc = NovelChapter.query.get(sm.novel_chapter_id)
            proj_id = nc.project_id if nc else None
        if proj_id != project_id:
            continue
        result.append({
            "id": sm.id,
            "filename": sm.filename,
            "shot_count": sm.shot_count or 0,
            "created_time": sm.created_time.strftime("%Y-%m-%d %H:%M") if sm.created_time else "",
        })
    result.sort(key=lambda x: x["filename"])
    return jsonify(result)


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

    # 可选：从灵感(从零开始) / 已有大纲(导入) 自动构建 世界观 + 人物 + 大纲
    # 为避免长耗时 LLM 调用阻塞创建请求（且防止客户端断开导致设定丢失），
    # 项目创建后立即返回，AI 推导在后台线程完成并写库。
    settings_building = False
    settings_note = ""
    mode = data.get("mode")
    seed = (data.get("inspiration") or data.get("source_text") or "").strip()
    if mode in ("scratch", "import") and seed:
        if os.environ.get("AI_DIRECTOR_OFFLINE", "0") == "1":
            settings_note = "当前为离线模式，未自动生成设定；联网后在创作工作台点「🤖 自动补充设定」即可。"
        else:
            settings_building = True
            settings_note = "项目已创建，AI 正在后台生成初始世界观 / 人物 / 大纲，稍后进入创作工作台即可看到。"
            import threading
            app = current_app._get_current_object()
            t = threading.Thread(target=_build_settings_async, args=(app, project.id, seed), daemon=True)
            t.start()

    resp = project.to_dict()
    resp["settings_building"] = settings_building
    resp["settings_note"] = settings_note
    return jsonify(resp), 201


def _build_settings_async(app, project_id, seed):
    """后台线程：由灵感/已有大纲推导 世界观 + 角色 + 大纲 并安全写库。"""
    with app.app_context():
        try:
            from web.services.novel_ai_service import derive_settings_from_novel
            from web.models.novel_models import WorldSetting, NovelCharacter, PlotOutline
            from web.models.database import db as _db
            result = derive_settings_from_novel(seed, project_id=project_id)
            world_in = result.get("world", {}) or {}
            chars_in = result.get("characters", []) or []
            outline_in = result.get("outline", {}) or {}

            # 世界观：补齐空字段
            world = WorldSetting.query.filter_by(project_id=project_id).first()
            if not world:
                world = WorldSetting(project_id=project_id)
                _db.session.add(world)
            for f in ["name", "world_type", "era", "geography", "power_system",
                      "social_structure", "history", "rules", "culture", "ai_context"]:
                v = (world_in.get(f) or "").strip()
                if v and not (getattr(world, f) or "").strip():
                    setattr(world, f, v)
            _db.session.flush()

            # 角色：只新增无同名者
            existing_names = {c.name for c in NovelCharacter.query.filter_by(project_id=project_id).all()}
            for c in chars_in:
                nm = (c.get("name") or "").strip()
                if not nm or nm in existing_names:
                    continue
                _db.session.add(NovelCharacter(
                    project_id=project_id, world_id=world.id, name=nm,
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
                ))
                existing_names.add(nm)

            # 大纲：没有才新建
            outline = PlotOutline.query.filter_by(project_id=project_id).first()
            if not outline:
                outline = PlotOutline(project_id=project_id)
                _db.session.add(outline)
            for f in ["logline", "theme", "synopsis", "conflict", "ending"]:
                v = (outline_in.get(f) or "").strip()
                if v and not (getattr(outline, f) or "").strip():
                    setattr(outline, f, v)

            _db.session.commit()
            app.logger.info(f"后台构建设定完成(项目 {project_id})")
        except Exception as e:
            _db.session.rollback()
            app.logger.warning(f"后台构建设定失败(项目 {project_id}): {e}")


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
