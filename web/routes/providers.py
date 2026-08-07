"""LLM 服务商配置 API"""
from flask import Blueprint, request, jsonify
from web.models.database import db, Provider
from web.services.llm_client import LLMClient

bp = Blueprint("providers", __name__)


@bp.route("", methods=["GET"])
def list_providers():
    providers = Provider.query.all()
    return jsonify([p.to_dict() for p in providers])


@bp.route("/<key>", methods=["GET"])
def get_provider(key):
    provider = Provider.query.get_or_404(key)
    return jsonify(provider.to_dict())


@bp.route("/<key>", methods=["PUT"])
def update_provider(key):
    provider = Provider.query.get(key)
    if not provider:
        provider = Provider(key=key, name=key, is_builtin=False)
        db.session.add(provider)

    data = request.get_json()
    if "api_key" in data:
        provider.api_key = data["api_key"]
    if "base_url" in data:
        provider.base_url = data["base_url"]
    if "name" in data:
        provider.name = data["name"]
    if "models" in data:
        provider.set_models(data["models"])

    db.session.commit()
    return jsonify(provider.to_dict())


@bp.route("/<key>/test", methods=["POST"])
def test_provider(key):
    """测试服务商连接"""
    provider = Provider.query.get(key)
    if not provider or not provider.api_key:
        return jsonify({"ok": False, "error": "未配置 API Key"})

    client = LLMClient(
        provider_key=key,
        api_key=provider.api_key,
        base_url=provider.base_url,
        model=provider.get_models()[0] if provider.get_models() else None,
    )
    result = client.chat([{"role": "user", "content": "你好，请回复OK"}], max_tokens=10)
    return jsonify({"ok": True, "response": result[:100]})


@bp.route("/models", methods=["GET"])
def list_all_models():
    """列出所有服务商的模型列表"""
    return jsonify(LLMClient.PROVIDER_MODELS)
