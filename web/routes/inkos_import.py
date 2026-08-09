"""inkos 回写接口：将 inkos 书籍目录导入 AI Director 创作库。"""
import os
import json

from flask import Blueprint, request, jsonify

bp = Blueprint("inkos_import", __name__)


@bp.route("/<int:project_id>/inkos-import", methods=["POST"])
def inkos_import(project_id):
    """把 inkos 书籍目录回写到本项目的小说创作库。

    Body: {
      "book_dir": "<inkos books/书名 目录绝对路径>",
      "source_tag": "inkos"(可选),
      "gen_appearance": true(默认) 是否用 LLM 生成角色外貌/视觉提示词,
      "auto_lock": false(默认) 是否自动开启主角一致性锁
    }
    会 upsert WorldSetting / PlotOutline / PlotPoint(五卷) / NovelCharacter / NovelChapter。
    """
    data = request.get_json(silent=True) or {}
    book_dir = (data.get("book_dir") or "").strip()
    source_tag = (data.get("source_tag") or "inkos").strip() or "inkos"
    gen_appearance = bool(data.get("gen_appearance", True))
    auto_lock = bool(data.get("auto_lock", False))

    if not book_dir:
        return jsonify({"error": "请提供 book_dir（inkos 书籍目录绝对路径）"}), 400
    if not os.path.isdir(book_dir):
        return jsonify({"error": f"目录不存在：{book_dir}"}), 400

    # 延迟导入，避免循环依赖与启动期加载
    from web.services.inkos_import import import_inkos_book

    try:
        stat = import_inkos_book(
            project_id, book_dir,
            source_tag=source_tag,
            gen_appearance=gen_appearance,
            auto_lock_main=auto_lock,
        )
    except Exception as e:
        return jsonify({"error": f"回写失败：{e}"}), 500

    return jsonify({"ok": True, "stat": stat})


@bp.route("/inkos-books", methods=["GET"])
def list_inkos_books():
    """探测本机 inkos 书籍目录（扫描常见位置下的 books/，含 book.json）。

    用于前端「导入 inkos 书籍」弹窗的下拉候选；找不到时用户仍可手填路径。
    """
    roots = []
    home = os.path.expanduser("~")
    roots.append(home)
    try:
        roots.append(os.getcwd())
    except Exception:
        pass
    try:
        for name in os.listdir(home):
            p = os.path.join(home, name)
            if os.path.isdir(p):
                roots.append(p)
    except Exception:
        pass

    books = []
    seen = set()

    def scan_books_dir(bdir):
        if not os.path.isdir(bdir):
            return
        for title in sorted(os.listdir(bdir)):
            bp = os.path.join(bdir, title)
            bj = os.path.join(bp, "book.json")
            if os.path.isfile(bj) and bp not in seen:
                seen.add(bp)
                try:
                    meta = json.loads(_safe_read(bj) or "{}")
                except Exception:
                    meta = {}
                books.append({"title": meta.get("title") or title, "dir": bp})

    for root in roots:
        scan_books_dir(os.path.join(root, "books"))
        # 再下探一层 root/*/books
        try:
            for name in os.listdir(root):
                scan_books_dir(os.path.join(root, name, "books"))
        except Exception:
            pass

    return jsonify({"ok": True, "books": books})


def _safe_read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""
