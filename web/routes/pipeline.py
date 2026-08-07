"""流水线 API"""
from flask import Blueprint, request, jsonify, current_app

bp = Blueprint("pipeline", __name__)


@bp.route("/run", methods=["POST"])
def run_pipeline():
    """提交流水线任务"""
    data = request.get_json()
    stage = data.get("stage", "run_all")
    project_name = data.get("project_name")
    chapter_id = data.get("chapter_id")
    script_id = data.get("script_id")

    task_manager = current_app.task_manager
    task_id = task_manager.submit(
        stage=stage,
        name=f"{stage} - {project_name or ''}",
        project_id=data.get("project_id"),
        chapter_id=chapter_id,
        project_name=project_name,
        script_id=script_id,
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
