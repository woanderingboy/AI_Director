"""章节管理 API"""
from flask import Blueprint, request, jsonify
from web.models.database import db, ChapterModel, ProjectModel

bp = Blueprint("chapters", __name__)


@bp.route("/projects/<int:project_id>/chapters", methods=["GET"])
def list_chapters(project_id):
    ProjectModel.query.get_or_404(project_id)
    chapters = ChapterModel.query.filter_by(project_id=project_id).order_by(ChapterModel.id).all()
    return jsonify([c.to_dict() for c in chapters])


@bp.route("/projects/<int:project_id>/chapters", methods=["POST"])
def create_chapter(project_id):
    ProjectModel.query.get_or_404(project_id)
    data = request.get_json()
    title = data.get("title", "").strip()
    content = data.get("content", "")
    filename = data.get("filename", f"{title}.txt")

    if not title:
        return jsonify({"error": "章节标题不能为空"}), 400

    chapter = ChapterModel(
        project_id=project_id,
        title=title,
        filename=filename,
        content=content,
    )
    db.session.add(chapter)
    db.session.commit()

    # 同时写入文件
    from flask import current_app
    import os
    root_path = current_app.config["ROOT_PATH"]
    story_dir = os.path.join(root_path, "02_Projects", ProjectModel.query.get(project_id).name, "04_Story")
    os.makedirs(story_dir, exist_ok=True)
    filepath = os.path.join(story_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return jsonify(chapter.to_dict()), 201


@bp.route("/chapters/<int:chapter_id>", methods=["GET"])
def get_chapter(chapter_id):
    chapter = ChapterModel.query.get_or_404(chapter_id)
    return jsonify(chapter.to_dict())


@bp.route("/chapters/<int:chapter_id>", methods=["PUT"])
def update_chapter(chapter_id):
    chapter = ChapterModel.query.get_or_404(chapter_id)
    data = request.get_json()
    if "title" in data:
        chapter.title = data["title"]
    if "content" in data:
        chapter.content = data["content"]
    db.session.commit()
    return jsonify(chapter.to_dict())


@bp.route("/chapters/<int:chapter_id>", methods=["DELETE"])
def delete_chapter(chapter_id):
    chapter = ChapterModel.query.get_or_404(chapter_id)
    db.session.delete(chapter)
    db.session.commit()
    return jsonify({"ok": True})
