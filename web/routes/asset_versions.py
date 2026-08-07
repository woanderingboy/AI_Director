"""资产版本管理 API"""
import json
import hashlib
from datetime import datetime
from flask import Blueprint, request, jsonify
from web.models.database import db
from web.models.asset_models import AssetVersion

bp = Blueprint("asset_versions", __name__)


def _make_hash(content):
    return hashlib.md5((content or "").encode()).hexdigest()[:12]


def _next_version_tag(project_id, asset_type, asset_key):
    """生成下一个版本号"""
    latest = AssetVersion.query.filter_by(
        project_id=project_id, asset_type=asset_type, asset_key=asset_key
    ).order_by(AssetVersion.created_time.desc()).first()
    if latest and latest.version_tag.startswith("v"):
        try:
            n = int(latest.version_tag[1:]) + 1
            return f"v{n}"
        except ValueError:
            pass
    return "v1"


@bp.route("/list", methods=["GET"])
def list_versions():
    """列出某资产的所有版本"""
    project_id = request.args.get("project_id", type=int)
    asset_type = request.args.get("asset_type", "")
    asset_key = request.args.get("asset_key", "")

    query = AssetVersion.query
    if project_id is not None:
        query = query.filter_by(project_id=project_id)
    else:
        query = query.filter(AssetVersion.project_id.is_(None))
    if asset_type:
        query = query.filter_by(asset_type=asset_type)
    if asset_key:
        query = query.filter_by(asset_key=asset_key)

    versions = query.order_by(AssetVersion.created_time.desc()).all()
    return jsonify([v.to_dict() for v in versions])


@bp.route("/save", methods=["POST"])
def save_version():
    """保存一个新版本"""
    data = request.get_json()
    project_id = data.get("project_id")  # None for global
    asset_type = data.get("asset_type", "")
    asset_key = data.get("asset_key", "")
    content = data.get("content", "")
    notes = data.get("notes", "")

    if not asset_type or not asset_key:
        return jsonify({"error": "asset_type 和 asset_key 必填"}), 400

    # 检查内容是否有变化
    content_hash = _make_hash(content)
    latest = AssetVersion.query.filter_by(
        project_id=project_id, asset_type=asset_type, asset_key=asset_key
    ).order_by(AssetVersion.created_time.desc()).first()

    if latest and latest.content_hash == content_hash:
        return jsonify({"message": "内容无变化，未创建新版本", "version": latest.to_dict()})

    version_tag = _next_version_tag(project_id, asset_type, asset_key)
    v = AssetVersion(
        project_id=project_id,
        asset_type=asset_type,
        asset_key=asset_key,
        version_tag=version_tag,
        content=content,
        content_hash=content_hash,
        notes=notes,
    )
    db.session.add(v)
    db.session.commit()
    return jsonify(v.to_dict()), 201


@bp.route("/<int:version_id>", methods=["GET"])
def get_version(version_id):
    """获取单个版本完整内容"""
    v = AssetVersion.query.get_or_404(version_id)
    return jsonify(v.to_dict_full())


@bp.route("/<int:version_id>", methods=["DELETE"])
def delete_version(version_id):
    """删除一个版本"""
    v = AssetVersion.query.get_or_404(version_id)
    if v.is_final:
        return jsonify({"error": "不能删除最终确认版本，请先取消确认"}), 400
    db.session.delete(v)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/confirm/<int:version_id>", methods=["POST"])
def confirm_final(version_id):
    """确认某个版本为最终版"""
    v = AssetVersion.query.get_or_404(version_id)

    # 取消同资产的其他最终版
    AssetVersion.query.filter_by(
        project_id=v.project_id, asset_type=v.asset_type, asset_key=v.asset_key, is_final=True
    ).update({"is_final": False})

    v.is_final = True
    db.session.commit()
    return jsonify({"ok": True, "message": f"{v.version_tag} 已确认为最终版"})


@bp.route("/confirm-batch", methods=["POST"])
def confirm_batch():
    """批量确认最终版"""
    data = request.get_json()
    version_ids = data.get("version_ids", [])
    count = 0
    for vid in version_ids:
        v = AssetVersion.query.get(vid)
        if v:
            AssetVersion.query.filter_by(
                project_id=v.project_id, asset_type=v.asset_type, asset_key=v.asset_key, is_final=True
            ).update({"is_final": False})
            v.is_final = True
            count += 1
    db.session.commit()
    return jsonify({"ok": True, "message": f"已批量确认 {count} 个版本"})


@bp.route("/delete-batch", methods=["POST"])
def delete_batch():
    """批量删除版本"""
    data = request.get_json()
    version_ids = data.get("version_ids", [])
    count = 0
    for vid in version_ids:
        v = AssetVersion.query.get(vid)
        if v and not v.is_final:
            db.session.delete(v)
            count += 1
    db.session.commit()
    return jsonify({"ok": True, "message": f"已删除 {count} 个版本"})


@bp.route("/unconfirm/<int:version_id>", methods=["POST"])
def unconfirm_final(version_id):
    """取消最终版确认"""
    v = AssetVersion.query.get_or_404(version_id)
    v.is_final = False
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/final", methods=["GET"])
def get_finals():
    """获取所有最终确认的版本"""
    project_id = request.args.get("project_id", type=int)
    asset_type = request.args.get("asset_type", "")

    query = AssetVersion.query.filter_by(is_final=True)
    if project_id is not None:
        query = query.filter_by(project_id=project_id)
    if asset_type:
        query = query.filter_by(asset_type=asset_type)

    finals = query.order_by(AssetVersion.asset_type, AssetVersion.asset_key).all()
    return jsonify([v.to_dict() for v in finals])


@bp.route("/summary", methods=["GET"])
def version_summary():
    """获取项目版本概况"""
    project_id = request.args.get("project_id", type=int)
    query = AssetVersion.query
    if project_id is not None:
        query = query.filter_by(project_id=project_id)

    all_versions = query.all()
    summary = {}
    for v in all_versions:
        key = f"{v.asset_type}:{v.asset_key}"
        if key not in summary:
            summary[key] = {
                "asset_type": v.asset_type,
                "asset_key": v.asset_key,
                "total_versions": 0,
                "final_version": None,
                "latest_tag": None,
            }
        summary[key]["total_versions"] += 1
        summary[key]["latest_tag"] = v.version_tag
        if v.is_final:
            summary[key]["final_version"] = v.version_tag

    return jsonify(list(summary.values()))


@bp.route("/clean", methods=["POST"])
def clean_versions():
    """清理所有版本记录"""
    deleted = AssetVersion.query.delete()
    db.session.commit()
    return jsonify({"ok": True, "message": f"已清理 {deleted} 条版本记录"})
