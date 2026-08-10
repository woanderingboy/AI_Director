"""流水线 API"""
import os
import sys
import json

from flask import Blueprint, request, jsonify, current_app

bp = Blueprint("pipeline", __name__)


@bp.route("/run", methods=["POST"])
def run_pipeline():
    """提交流水线任务（支持临时覆盖提示词/模型/温度等）"""
    data = request.get_json() or {}
    stage = data.get("stage", "run_all")
    project_name = data.get("project_name")
    chapter_id = data.get("chapter_id")
    script_id = data.get("script_id")

    # 临时覆盖项：仅当用户在生成界面显式填写时才透传，否则沿用项目/全局配置
    override_fields = {}
    for f in ("custom_prompt", "provider_key", "model", "temperature", "max_tokens"):
        if f in data and data[f] is not None and data[f] != "":
            override_fields[f] = data[f]

    task_manager = current_app.task_manager
    task_id = task_manager.submit(
        stage=stage,
        name=f"{stage} - {project_name or ''}",
        project_id=data.get("project_id"),
        chapter_id=chapter_id,
        project_name=project_name,
        script_id=script_id,
        **override_fields,
    )
    return jsonify({"task_id": task_id, "status": "submitted"})


@bp.route("/stages", methods=["GET"])
def list_stages():
    """列出可用的流水线阶段"""
    return jsonify([
        {"key": "pipeline.novel2script", "name": "小说→剧本", "desc": "将小说文本转换为结构化剧本"},
        {"key": "pipeline.gen_prompts", "name": "剧本→Prompt", "desc": "将剧本转换为视觉提示词"},
        {"key": "pipeline.draw_images", "name": "Prompt→图片", "desc": "生成AI图片"},
        {"key": "pipeline.render_videos", "name": "图片→视频", "desc": "合成视频"},
        {"key": "pipeline.run_all", "name": "一键全流程", "desc": "四阶段全部执行"},
    ])


@bp.route("/reset-prompt", methods=["POST"])
def reset_prompt():
    """重置某分镜提示词为系统默认版本：清除 is_final 与文件内 _locked 锁。
    下次 gen_prompts 重跑将重新生成默认提示词（用户手改/定版被丢弃）。"""
    data = request.get_json() or {}
    project_id = data.get("project_id")
    stem = data.get("stem")  # 例如 "第一章 离站_script_prompt_S01"
    if not project_id or not stem:
        return jsonify({"error": "project_id 与 stem 必填"}), 400
    from web.models.database import db, ProjectModel
    from web.models.asset_models import AssetVersion
    from web.paths import project_subdir
    p = ProjectModel.query.get(project_id)
    if not p:
        return jsonify({"error": "项目不存在"}), 404
    # 1) 清 DB 里的 is_final（取消预设/定版）
    AssetVersion.query.filter_by(
        project_id=project_id, asset_type="storyboard_prompt", asset_key=stem
    ).update({"is_final": False})
    db.session.commit()
    # 2) 清文件内 _locked（释放手改锁）
    prompt_dir = project_subdir(p.name, "prompt")
    fp = os.path.join(prompt_dir, stem + ".json")
    file_existed = os.path.exists(fp)
    changed = False
    if file_existed:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and d.get("_locked"):
                d["_locked"] = False
                with open(fp, "w", encoding="utf-8") as f:
                    json.dump(d, f, ensure_ascii=False, indent=2)
                changed = True
        except Exception:
            pass
    return jsonify({
        "ok": True, "reset": stem, "file_existed": file_existed, "changed": changed,
        "message": "已重置为系统默认版本；下次 gen_prompts 重跑将重新生成该分镜提示词"
    })
