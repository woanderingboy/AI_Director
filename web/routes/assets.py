"""项目资产 API"""
from flask import Blueprint, request, jsonify, current_app

bp = Blueprint("assets", __name__)


@bp.route("/<project_name>", methods=["GET"])
def list_project_assets(project_name):
    from web.services.project_service import ProjectService
    svc = ProjectService(current_app.config["ROOT_PATH"])
    category = request.args.get("category", "all")
    if category == "all":
        result = {}
        for cat in ["story", "script", "storyboard", "prompt", "image", "video"]:
            result[cat] = svc.get_project_files(project_name, cat)
        return jsonify(result)
    return jsonify(svc.get_project_files(project_name, category))
