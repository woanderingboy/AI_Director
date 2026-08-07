"""全局资产库 API + AI 学习功能"""
import os
import yaml
from flask import Blueprint, request, jsonify, current_app

bp = Blueprint("global_assets_enhanced", __name__)


@bp.route("", methods=["GET"])
def list_assets():
    """列出所有全局资产"""
    from core.global_asset_loader import GlobalAssetLoader
    loader = GlobalAssetLoader(current_app.config["ROOT_PATH"])
    category = request.args.get("category")
    if category:
        return jsonify(loader.list_category(category))
    return jsonify(loader.list_all())


@bp.route("/<category>/<filename>", methods=["GET"])
def get_asset(category, filename):
    from core.global_asset_loader import GlobalAssetLoader
    loader = GlobalAssetLoader(current_app.config["ROOT_PATH"])
    asset = loader.load_asset(category, filename)
    if asset is None:
        return jsonify({"error": "资产不存在"}), 404
    return jsonify(asset)


@bp.route("/<category>", methods=["POST"])
def save_asset(category):
    from core.global_asset_loader import GlobalAssetLoader
    loader = GlobalAssetLoader(current_app.config["ROOT_PATH"])
    data = request.get_json()
    filename = data.get("filename", "")
    content = data.get("content", {})
    if not filename:
        return jsonify({"error": "文件名不能为空"}), 400
    loader.save_asset(category, filename, content)
    return jsonify({"ok": True, "path": f"{category}/{filename}"})


@bp.route("/<category>/<filename>", methods=["DELETE"])
def delete_asset(category, filename):
    """删除全局资产"""
    root_path = current_app.config["ROOT_PATH"]
    filepath = os.path.join(root_path, "01_Global_Assets", category, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        return jsonify({"ok": True})
    return jsonify({"error": "文件不存在"}), 404


@bp.route("/suggest", methods=["POST"])
def suggest_from_finals():
    """AI 分析最终版素材，建议丰富全局资产库"""
    from web.models.asset_models import AssetVersion
    from web.models.database import ProjectConfig

    data = request.get_json() or {}
    project_id = data.get("project_id")

    # 收集所有最终确认的版本
    finals = AssetVersion.query.filter_by(is_final=True).all()
    if project_id:
        finals = [f for f in finals if f.project_id == project_id]

    if not finals:
        return jsonify({"suggestions": [], "message": "没有找到最终确认的素材"})

    # 收集素材内容摘要
    summaries = []
    for f in finals:
        summaries.append(f"[{f.asset_type}] {f.asset_key}: {f.content[:200]}")

    context = "\n".join(summaries)

    # 调用 LLM 分析
    from web.services.llm_client import LLMClient
    from web.models.database import Provider

    provider = Provider.query.filter(Provider.api_key != "").first()
    if not provider:
        return jsonify({"suggestions": [], "message": "未配置 LLM API Key"})

    client = LLMClient(provider.key, provider.api_key)

    prompt = f"""你是一名专业的影视资产顾问。根据用户最终确认的素材，分析其中的风格特征，建议可以添加到全局资产库的新条目。

当前素材摘要：
{context}

全局资产库分类：
- Camera（运镜）：全景/中景/近景/特写/推/拉/摇/跟拍/航拍等
- Transition（转场）：硬切/淡入淡出/叠化/擦除等
- Emotion（情绪）：紧张/温馨/压抑/史诗/孤独等
- Lighting（灯光）：侧逆光/柔光/硬光/自然光等
- Style（风格）：写实/动漫/赛博朋克/水墨等
- Action（动作）：对话/追逐/打斗/独白等

请分析素材特征，建议新增的资产条目。输出 JSON：
```json
{{
  "analysis": "风格特征分析",
  "suggestions": [
    {{
      "category": "Camera/Transition/Emotion/Lighting/Style/Action",
      "name": "资产名称",
      "description": "描述",
      "prompt": "提示词关键词",
      "reason": "为什么建议添加"
    }}
  ]
}}
```"""

    result = client.chat_json([{"role": "user", "content": prompt}], max_tokens=2048)
    return jsonify(result if isinstance(result, dict) else {"raw": result})


@bp.route("/apply-suggestion", methods=["POST"])
def apply_suggestion():
    """应用 AI 建议，添加到全局资产库"""
    from core.global_asset_loader import GlobalAssetLoader

    data = request.get_json()
    category = data.get("category", "")
    name = data.get("name", "")
    content = data.get("content", {})

    if not category or not name:
        return jsonify({"error": "缺少分类或名称"}), 400

    loader = GlobalAssetLoader(current_app.config["ROOT_PATH"])
    filename = f"{name}.yaml"
    loader.save_asset(category, filename, content)
    return jsonify({"ok": True, "path": f"{category}/{filename}"})
