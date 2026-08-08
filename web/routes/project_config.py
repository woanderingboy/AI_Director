"""项目配置 API - 全局 + 各阶段独立配置"""
from flask import Blueprint, request, jsonify
from web.models.database import db, ProjectConfig
import json

bp = Blueprint("project_config", __name__)

# 所有可配置的阶段
STAGES = {
    "novel2script": "小说→剧本（流水线）",
    "gen_prompts": "剧本→提示词（流水线）",
    "draw_images": "生成图片（流水线）",
    "render_videos": "渲染视频（流水线）",
    "world": "🌍 世界观设定",
    "character": "👥 人物设计",
    "outline": "📋 剧情大纲",
    "plotpoints": "🎯 关键节点",
    "chapters": "📖 章节概要",
    "scenes": "🎬 场景正文",
    "polish": "✨ 润色修改",
    "chat": "💬 AI 对话",
}


@bp.route("/stages", methods=["GET"])
def list_stages():
    """列出所有可配置阶段"""
    return jsonify(STAGES)


@bp.route("/prompt-templates", methods=["GET"])
def prompt_templates():
    """返回各阶段的标准默认指令模版（用户自定义会叠加在默认之后，可在此基础上修改）。"""
    from web.services.prompt_templates import DEFAULT_PROMPTS
    data = {}
    for key, label in STAGES.items():
        data[key] = {
            "label": label,
            "default": DEFAULT_PROMPTS.get(key, ""),
        }
    return jsonify(data)


@bp.route("/projects/<int:project_id>/config", methods=["GET"])
def get_config(project_id):
    config = ProjectConfig.query.filter_by(project_id=project_id).first()
    if not config:
        return jsonify({
            "project_id": project_id,
            "provider_key": "",
            "model": "",
            "temperature": 0.7,
            "max_tokens": 4096,
            "system_prompts": {},
            "llm_configs": {},
        })
    return jsonify(config.to_dict())


@bp.route("/projects/<int:project_id>/config", methods=["PUT"])
def update_config(project_id):
    data = request.get_json()
    config = ProjectConfig.query.filter_by(project_id=project_id).first()
    if not config:
        config = ProjectConfig(project_id=project_id)
        db.session.add(config)

    if "provider_key" in data:
        config.provider_key = data["provider_key"]
    if "model" in data:
        config.model = data["model"]
    if "temperature" in data:
        config.temperature = data["temperature"]
    if "max_tokens" in data:
        config.max_tokens = data["max_tokens"]
    if "system_prompts" in data:
        config.system_prompts = json.dumps(data["system_prompts"], ensure_ascii=False)
    if "llm_configs" in data:
        config.llm_configs = json.dumps(data["llm_configs"], ensure_ascii=False)

    db.session.commit()
    return jsonify(config.to_dict())


@bp.route("/projects/<int:project_id>/config/stage/<stage>", methods=["GET"])
def get_stage_config(project_id, stage):
    """获取单个阶段的配置"""
    config = ProjectConfig.query.filter_by(project_id=project_id).first()
    if not config:
        return jsonify({"stage": stage, "model": "", "temperature": None, "max_tokens": None, "system_prompt": ""})

    stage_configs = json.loads(config.llm_configs) if config.llm_configs else {}
    prompts = json.loads(config.system_prompts) if config.system_prompts else {}
    sc = stage_configs.get(stage, {})

    return jsonify({
        "stage": stage,
        "provider_key": sc.get("provider_key", ""),
        "model": sc.get("model", ""),
        "temperature": sc.get("temperature"),
        "max_tokens": sc.get("max_tokens"),
        "system_prompt": prompts.get(stage, ""),
    })


@bp.route("/projects/<int:project_id>/config/stage/<stage>", methods=["PUT"])
def update_stage_config(project_id, stage):
    """更新单个阶段的配置"""
    data = request.get_json()
    config = ProjectConfig.query.filter_by(project_id=project_id).first()
    if not config:
        config = ProjectConfig(project_id=project_id)
        db.session.add(config)

    # 更新阶段模型配置
    stage_configs = json.loads(config.llm_configs) if config.llm_configs else {}
    sc = stage_configs.get(stage, {})
    for field in ["provider_key", "model", "temperature", "max_tokens"]:
        if field in data and data[field] is not None and data[field] != "":
            sc[field] = data[field]
    stage_configs[stage] = sc
    config.llm_configs = json.dumps(stage_configs, ensure_ascii=False)

    # 更新阶段 system prompt
    if "system_prompt" in data:
        prompts = json.loads(config.system_prompts) if config.system_prompts else {}
        prompts[stage] = data["system_prompt"]
        config.system_prompts = json.dumps(prompts, ensure_ascii=False)

    db.session.commit()
    return jsonify({"ok": True, "stage": stage})
