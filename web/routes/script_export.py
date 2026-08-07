"""剧本导出端点：将 05_Script 下的剧本 JSON 导出为 Fountain / FDX 文件下载。"""
import os
from urllib.parse import quote

from flask import Blueprint, Response, abort

from web.services.fountain_export import build_blocks, to_fountain, to_fdx

bp = Blueprint("script_export", __name__)

# D:\AI_Director  (web/routes -> web -> D:\AI_Director)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _project_id_from_name(project_name):
    """按项目名反查 project_id（查不到返回 None，导出注释会跳过）。"""
    try:
        from web.models.database import ProjectModel
        p = ProjectModel.query.filter_by(name=project_name).first()
        return p.id if p else None
    except Exception:
        return None


@bp.route("/<fmt>/<project_name>/<path:filename>")
def export_script(fmt, project_name, filename):
    if fmt not in ("fountain", "fdx"):
        abort(404)

    script_dir = os.path.normpath(os.path.join(ROOT, "02_Projects", project_name, "05_Script"))
    filepath = os.path.normpath(os.path.join(script_dir, filename))

    # 防目录穿越：必须落在 05_Script 目录内
    if not filepath.startswith(script_dir) or not os.path.isfile(filepath):
        abort(404)

    try:
        import json
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        abort(404)

    # 角色一致性锁信息：查询角色库，仅「已锁定」角色写入导出注释（供真人编剧对照）
    char_meta = {}
    try:
        from web.models.novel_models import NovelCharacter
        chars = NovelCharacter.query.filter_by(
            project_id=_project_id_from_name(project_name)
        ).all()
        for c in chars:
            if getattr(c, "consistency_lock", False):
                char_meta[c.name] = {
                    "locked": True,
                    "appearance": (c.appearance or "").strip(),
                    "locked_prompt": (c.locked_prompt or "").strip(),
                }
    except Exception:
        char_meta = {}

    blocks = build_blocks(data, char_meta=char_meta or None)
    base = os.path.splitext(filename)[0]
    if fmt == "fountain":
        content = to_fountain(blocks)
        mime = "text/plain"
        out_name = base + ".fountain"
    else:
        content = to_fdx(blocks)
        mime = "application/xml"
        out_name = base + ".fdx"

    # RFC 5987：让中文文件名在各浏览器都能正确保存
    disp = f"attachment; filename*=UTF-8''{quote(out_name)}"
    resp = Response(content, mimetype=mime)
    resp.headers["Content-Disposition"] = disp
    resp.charset = "utf-8"
    return resp
