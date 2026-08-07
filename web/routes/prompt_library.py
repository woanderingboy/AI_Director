"""Prompt 词库 API"""
from flask import Blueprint, request, jsonify
from web.models.database import db, PromptTerm

bp = Blueprint("prompt_library", __name__)


@bp.route("", methods=["GET"])
def list_terms():
    category = request.args.get("category")
    query = PromptTerm.query
    if category:
        query = query.filter_by(category=category)
    terms = query.order_by(PromptTerm.use_count.desc()).all()
    return jsonify([t.to_dict() for t in terms])


@bp.route("", methods=["POST"])
def add_term():
    data = request.get_json()
    term = data.get("term", "").strip()
    if not term:
        return jsonify({"error": "词条不能为空"}), 400
    t = PromptTerm(
        term=term,
        category=data.get("category", ""),
        manual_weight=data.get("manual_weight", 1.0),
    )
    db.session.add(t)
    db.session.commit()
    return jsonify(t.to_dict()), 201


@bp.route("/<int:term_id>", methods=["DELETE"])
def delete_term(term_id):
    t = PromptTerm.query.get_or_404(term_id)
    db.session.delete(t)
    db.session.commit()
    return jsonify({"ok": True})
