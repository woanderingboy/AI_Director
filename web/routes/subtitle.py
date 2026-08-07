"""字幕模块路由：字体列表 / 视频列表 / 语音识别 / 烧录导出。

流程（满足「手动确认后再加入」）：
  GET  /api/subtitle/fonts                —— 可用中文字体
  GET  /api/subtitle/<pid>/videos         —— 项目 09_Video 下的视频
  POST /api/subtitle/transcribe           —— 仅识别并返回段落（不写任何产物）
  POST /api/subtitle/render               —— 按用户确认后的段落+样式 烧录并写 SRT
"""
import os

from flask import Blueprint, jsonify, request, current_app

from web.models.database import ProjectModel
from web.services.subtitle_service import (
    SubtitleError,
    burn_subtitles,
    extract_audio,
    list_cjk_fonts,
    list_project_videos,
    project_videos_dir,
    transcribe,
)

bp = Blueprint("subtitle", __name__, url_prefix="/api/subtitle")


def _project_video_path(project_id, video):
    project = ProjectModel.query.get(project_id)
    if not project:
        return None, None
    d = project_videos_dir(project.name)
    if not video:
        videos = list_project_videos(project.name)
        if not videos:
            return project.name, None
        video = videos[0]
    path = os.path.normpath(os.path.join(d, video))
    if not path.startswith(d) or not os.path.isfile(path):
        return project.name, None
    return project.name, path


@bp.route("/fonts", methods=["GET"])
def fonts():
    return jsonify({"fonts": list_cjk_fonts()})


@bp.route("/<int:project_id>/videos", methods=["GET"])
def videos(project_id):
    project = ProjectModel.query.get(project_id)
    if not project:
        return jsonify({"error": "项目不存在"}), 404
    items = list_project_videos(project.name)
    default = None
    if items:
        preview = f"{project.name}_preview.mp4"
        default = preview if preview in items else items[0]
    return jsonify({"project": project.name, "videos": items, "default": default})


@bp.route("/transcribe", methods=["POST"])
def do_transcribe():
    data = request.get_json(silent=True) or {}
    project_id = data.get("project_id")
    video = data.get("video")
    model_size = data.get("model_size", "small")
    if not project_id:
        return jsonify({"error": "缺少 project_id"}), 400

    project_name, video_path = _project_video_path(project_id, video)
    if not video_path:
        return jsonify({"error": "未找到视频文件", "project": project_name}), 404

    try:
        wav_path, has_audio = extract_audio(video_path)
        if not has_audio:
            return jsonify({
                "segments": [],
                "engine": "whisper",
                "has_audio": False,
                "note": "视频无音轨（可能是静帧幻灯片），无法自动识别语音。"
                        "你可以在下方手动添加字幕行。",
            })
        segments = transcribe(wav_path, model_size=model_size, language="zh")
        note = None
        if not segments:
            note = "未检测到语音内容。若为无声视频，请在下方手动添加字幕行。"
        return jsonify({
            "segments": segments,
            "engine": "whisper",
            "has_audio": True,
            "note": note,
            "count": len(segments),
        })
    except SubtitleError as e:
        return jsonify({
            "segments": [],
            "engine": "whisper",
            "has_audio": None,
            "note": str(e),
            "error": str(e),
        }), 200
    except Exception as e:  # noqa: BLE001
        # 识别失败（如模型首次下载受网络限制）不应阻断界面：返回说明，用户仍可手动添加字幕
        return jsonify({
            "segments": [],
            "engine": "whisper",
            "has_audio": None,
            "asr_error": True,
            "note": f"自动识别暂不可用：{e}。"
                    f"若首次使用，whisper 模型需联网从 HuggingFace 下载（权重文件走 LFS CDN）。"
                    f"请确认网络可访问 cdn-lfs.hf.co / cdn-lfs.hf-mirror.com，或在可联网环境首次运行一次。"
                    f"你仍可在下方手动添加字幕行。",
        }), 200


@bp.route("/render", methods=["POST"])
def do_render():
    data = request.get_json(silent=True) or {}
    project_id = data.get("project_id")
    video = data.get("video")
    segments = data.get("segments")
    style = data.get("style") or {}
    if not project_id:
        return jsonify({"error": "缺少 project_id"}), 400
    if not isinstance(segments, list) or not segments:
        return jsonify({"error": "缺少字幕段落（segments）"}), 400

    project_name, video_path = _project_video_path(project_id, video)
    if not video_path:
        return jsonify({"error": "未找到视频文件", "project": project_name}), 404

    try:
        out_path, srt_path = burn_subtitles(video_path, segments, style=style)
        # 返回相对 02_Projects 的路径，便于前端拼播放/下载 URL
        rel = os.path.relpath(out_path, current_app.config.get("ROOT_PATH", os.getcwd()))
        rel_srt = os.path.relpath(srt_path, current_app.config.get("ROOT_PATH", os.getcwd())) if srt_path else None
        return jsonify({
            "video_out": rel.replace("\\", "/"),
            "srt_out": rel_srt.replace("\\", "/") if rel_srt else None,
            "count": len(segments),
            "video_file": os.path.basename(out_path),
            "srt_file": os.path.basename(srt_path) if srt_path else None,
        })
    except SubtitleError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"烧录失败：{e}"}), 500
