"""项目级全局设定 - 含人物形象系统（多状态服装）"""
from flask import Blueprint, request, jsonify
from web.models.database import db, ProjectConfig
from web.services.prompt_assembly import get_project_globals
import json

bp = Blueprint("project_globals", __name__)


@bp.route("/projects/<int:project_id>/globals", methods=["GET"])
def get_globals(project_id):
    globals_data = get_project_globals(project_id)
    return jsonify({**_default_globals(), **globals_data})


@bp.route("/projects/<int:project_id>/globals", methods=["PUT"])
def update_globals(project_id):
    data = request.get_json()
    config = ProjectConfig.query.filter_by(project_id=project_id).first()
    if not config:
        config = ProjectConfig(project_id=project_id)
        db.session.add(config)
    prompts = json.loads(config.system_prompts) if config.system_prompts else {}
    prompts["__globals__"] = data
    config.system_prompts = json.dumps(prompts, ensure_ascii=False)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/projects/<int:project_id>/globals/characters", methods=["GET"])
def get_character_profiles(project_id):
    """获取项目角色视觉档案"""
    config = ProjectConfig.query.filter_by(project_id=project_id).first()
    if not config:
        return jsonify({})
    globals_data = json.loads(config.system_prompts).get("__globals__", {}) if config.system_prompts else {}
    return jsonify(globals_data.get("character_profiles", {}))


@bp.route("/projects/<int:project_id>/globals/characters/<name>", methods=["PUT"])
def update_character_profile(project_id, name):
    """更新单个角色视觉档案"""
    data = request.get_json()
    config = ProjectConfig.query.filter_by(project_id=project_id).first()
    if not config:
        config = ProjectConfig(project_id=project_id)
        db.session.add(config)
    prompts = json.loads(config.system_prompts) if config.system_prompts else {}
    if "__globals__" not in prompts:
        prompts["__globals__"] = {}
    if "character_profiles" not in prompts["__globals__"]:
        prompts["__globals__"]["character_profiles"] = {}
    prompts["__globals__"]["character_profiles"][name] = data
    config.system_prompts = json.dumps(prompts, ensure_ascii=False)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/projects/<int:project_id>/globals/characters/<name>/outfit", methods=["POST"])
def add_outfit(project_id, name):
    """为角色添加新服装状态"""
    data = request.get_json()
    outfit_name = data.get("name", "")
    if not outfit_name:
        return jsonify({"error": "服装名称不能为空"}), 400

    config = ProjectConfig.query.filter_by(project_id=project_id).first()
    if not config:
        return jsonify({"error": "项目配置不存在"}), 404

    prompts = json.loads(config.system_prompts) if config.system_prompts else {}
    profiles = prompts.get("__globals__", {}).get("character_profiles", {})
    if name not in profiles:
        profiles[name] = {"outfits": {}}
    if "outfits" not in profiles[name]:
        profiles[name]["outfits"] = {}
    profiles[name]["outfits"][outfit_name] = {
        "description": data.get("description", ""),
        "prompt": data.get("prompt", ""),
        "scene_context": data.get("scene_context", ""),
    }
    prompts.setdefault("__globals__", {})["character_profiles"] = profiles
    config.system_prompts = json.dumps(prompts, ensure_ascii=False)
    db.session.commit()
    return jsonify({"ok": True})


def _default_globals():
    return {
        # 视觉风格
        "art_style": "",
        "color_palette": "",
        "lighting": "",
        "mood": "",
        # 提示词
        "positive_prompts": "",
        "negative_prompts": "",
        # 输出参数
        "resolution": "1080p",
        "fps": 24,
        "aspect_ratio": "16:9",
        # 角色视觉档案（按角色名索引）
        "character_profiles": {},
    }
