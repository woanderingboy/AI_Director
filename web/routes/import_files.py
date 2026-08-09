"""文件导入 API - 扫描文件夹识别内容并建库（小说 / 剧本 / 资产图改名导入）

设计：
- 小说：把 .txt/.md 放进 02_Projects/{项目}/04_Story/，按章节标题自动拆分，批量建 NovelChapter。
- 剧本：把剧本 JSON 放进 02_Projects/{项目}/03_Import/，复制到 05_Script 并建 ScriptModel（按标题联动章节）。
- 资产图：上传图片时可自定义文件名存入 08_Image（文件名关系到资产匹配关键词，故支持改名）。
- 全部带去重（按文件名+内容哈希），重复扫描不会重复建库。
"""
import os
import re
import json
import hashlib
import shutil

from flask import Blueprint, request, jsonify, current_app
from web.models.database import db
from web.models.novel_models import NovelChapter
from web.paths import PROJECT_SUBDIRS

bp = Blueprint("import_files", __name__)

# 章节标题识别：第X章/回/节/卷/部/篇/集/幕、Chapter N、Markdown # 标题、卷X
CHAPTER_RE = re.compile(
    r"^\s*(?:"
    r"第\s*[0-9零一二三四五六七八九十百千两]+\s*[章回节卷部篇集幕]|"
    r"chapter\s+\d+|chapter\s+[ivxlcdm]+|"
    r"#{1,6}\s+.+|"
    r"卷\s*[一二三四五六七八九十0-9]+"
    r")",
    re.IGNORECASE,
)


def _sub(proj_path, cat):
    """返回 02_Projects/<项目>/<cat 对应子目录>；cat 为 PROJECT_SUBDIRS 的键。"""
    return os.path.join(proj_path, PROJECT_SUBDIRS[cat])


def _proj_path(project_id):
    from web.models.database import ProjectModel
    p = ProjectModel.query.get(project_id)
    if not p:
        return None, None
    return p, os.path.join(current_app.config["ROOT_PATH"], "02_Projects", p.name)


def _marker_path(folder, kind):
    return os.path.join(folder, f"._imported_{kind}.json")


def _read_marker(folder, kind):
    mp = _marker_path(folder, kind)
    if os.path.exists(mp):
        try:
            return json.load(open(mp, encoding="utf-8"))
        except Exception:
            pass
    return {}


def _write_marker(folder, kind, data):
    with open(_marker_path(folder, kind), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _split_novel(text):
    """把整篇文本按标题拆成 [{title, content}] 章节列表。"""
    lines = text.splitlines()
    chapters = []
    cur_title = None
    cur_lines = []
    for ln in lines:
        if CHAPTER_RE.match(ln):
            if cur_title is not None or cur_lines:
                chapters.append({
                    "title": (cur_title or f"第{len(chapters) + 1}章").strip(),
                    "content": "\n".join(cur_lines).strip(),
                })
            cur_title = re.sub(r"^#+\s*", "", ln).strip()
            cur_lines = []
        else:
            cur_lines.append(ln)
    if cur_title is not None or cur_lines:
        chapters.append({
            "title": (cur_title or f"第{len(chapters) + 1}章").strip(),
            "content": "\n".join(cur_lines).strip(),
        })
    if not chapters:
        chapters.append({"title": None, "content": text.strip()})
    return chapters


def _next_chapter_number(project_id):
    mx = db.session.query(db.func.max(NovelChapter.chapter_number)).filter_by(
        project_id=project_id
    ).scalar() or 0
    return mx


@bp.route("/<int:project_id>/scan-novels", methods=["POST"])
def scan_novels(project_id):
    """扫描 04_Story/ 下的 .txt/.md，按标题拆分章节并建库。"""
    proj, proj_path = _proj_path(project_id)
    if not proj:
        return jsonify({"error": "项目不存在"}), 404
    story_dir = _sub(proj_path, "story")
    os.makedirs(story_dir, exist_ok=True)
    marker = _read_marker(story_dir, "novel")
    imported, skipped = [], []
    existing = {c.title for c in NovelChapter.query.filter_by(project_id=project_id).all()}
    num = _next_chapter_number(project_id)

    for fn in sorted(os.listdir(story_dir)):
        if not fn.lower().endswith((".txt", ".md")) or fn.startswith("._"):
            continue
        fp = os.path.join(story_dir, fn)
        if not os.path.isfile(fp):
            continue
        raw = open(fp, encoding="utf-8", errors="ignore").read()
        h = hashlib.md5(raw.encode("utf-8", "ignore")).hexdigest()[:12]
        if marker.get(fn) == h:
            skipped.append(fn)
            continue
        for ch in _split_novel(raw):
            title = (ch["title"] or os.path.splitext(fn)[0])[:200]
            if title in existing:
                continue
            num += 1
            nc = NovelChapter(
                project_id=project_id, chapter_number=num, title=title,
                summary="", content=ch["content"], status="draft",
            )
            nc.word_count = len(ch["content"] or "")
            db.session.add(nc)
            existing.add(title)
            imported.append(title)
        marker[fn] = h

    db.session.commit()
    _write_marker(story_dir, "novel", marker)
    return jsonify({
        "ok": True, "imported": imported, "imported_count": len(imported),
        "skipped": skipped, "story_dir": story_dir,
        "message": f"成功导入 {len(imported)} 个章节"
        + (f"，跳过已导入 {len(skipped)} 个文件" if skipped else ""),
    })


@bp.route("/<int:project_id>/scan-scripts", methods=["POST"])
def scan_scripts(project_id):
    """扫描 03_Import/ 下的剧本 JSON，复制到 05_Script 并建库（按标题联动章节）。"""
    proj, proj_path = _proj_path(project_id)
    if not proj:
        return jsonify({"error": "项目不存在"}), 404
    import_dir = _sub(proj_path, "import")
    script_dir = _sub(proj_path, "script")
    os.makedirs(import_dir, exist_ok=True)
    os.makedirs(script_dir, exist_ok=True)
    marker = _read_marker(import_dir, "script")
    imported, skipped = [], []
    chapters = NovelChapter.query.filter_by(project_id=project_id).all()
    title2ch = {c.title: c for c in chapters}
    num = _next_chapter_number(project_id)

    for fn in sorted(os.listdir(import_dir)):
        if not fn.lower().endswith(".json") or fn.startswith("._"):
            continue
        fp = os.path.join(import_dir, fn)
        if not os.path.isfile(fp):
            continue
        try:
            data = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or ("scenes" not in data and "shots" not in data):
            continue
        raw = open(fp, encoding="utf-8", errors="ignore").read()
        h = hashlib.md5(raw.encode("utf-8", "ignore")).hexdigest()[:12]
        if marker.get(fn) == h:
            skipped.append(fn)
            continue

        base = os.path.splitext(fn)[0].replace("_script", "")
        ch = title2ch.get(base) or title2ch.get(os.path.splitext(fn)[0])
        if not ch:
            num += 1
            ch = NovelChapter(
                project_id=project_id, chapter_number=num, title=base[:200],
                summary="", content="", status="draft",
            )
            ch.word_count = 0
            db.session.add(ch)
            db.session.flush()
            title2ch[base] = ch

        dst = os.path.join(script_dir, fn)
        if not os.path.exists(dst):
            shutil.copy2(fp, dst)
        from web.models.database import ScriptModel
        sm = ScriptModel(
            chapter_id=None, novel_chapter_id=ch.id,
            filename=fn, file_path=dst,
            shot_count=len(data.get("shots", [])) or len(data.get("scenes", [])),
        )
        db.session.add(sm)
        imported.append(fn)
        marker[fn] = h

    db.session.commit()
    _write_marker(import_dir, "script", marker)
    return jsonify({
        "ok": True, "imported": imported, "imported_count": len(imported),
        "skipped": skipped,
        "message": f"成功导入 {len(imported)} 个剧本"
        + (f"，跳过已导入 {len(skipped)} 个文件" if skipped else ""),
    })


@bp.route("/<int:project_id>/import-image", methods=["POST"])
def import_image(project_id):
    """上传资产图并支持自定义文件名存入 08_Image（文件名关系到资产匹配关键词）。"""
    proj, proj_path = _proj_path(project_id)
    if not proj:
        return jsonify({"error": "项目不存在"}), 404
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "缺少文件"}), 400

    name = (request.form.get("asset_name") or os.path.splitext(file.filename)[0] or "asset").strip()
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name)[:120]
    ext = os.path.splitext(file.filename)[1].lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
        ext = ".png"

    image_dir = _sub(proj_path, "image")
    os.makedirs(image_dir, exist_ok=True)
    dst = os.path.join(image_dir, name + ext)
    if os.path.exists(dst):
        base, e = os.path.splitext(dst)
        i = 1
        while os.path.exists(f"{base}_{i}{e}"):
            i += 1
        dst = f"{base}_{i}{e}"
    file.save(dst)
    return jsonify({
        "ok": True, "filename": os.path.basename(dst), "path": dst,
        "message": f"已导入图片：{os.path.basename(dst)}",
    })


@bp.route("/<int:project_id>/import-package", methods=["POST"])
def import_package(project_id):
    """重新导入一个「已导出的素材打包文件夹」到本项目（闭环「打包导出 → 直接导入」）。

    导出文件夹结构（见 asset_packages.export）：
      - prompts/*.json   分镜提示词（原 07_Prompt 内容）
      - <图片/视频文件>   资产（根目录，按扩展名区分）
      - index.json        清单（跳过，不导入）

    行为：
      - prompts/*.json → 02_Projects/{项目}/07_Prompt/
      - 图片           → 08_Image/
      - 视频           → 09_Video/
      - 幂等：同名文件已存在则跳过（记 skipped），不覆盖用户既有产物。
    仅做文件落地；分镜画布/打包分析均为读盘驱动，导入后即可直接查看与再次打包。
    """
    proj, proj_path = _proj_path(project_id)
    if not proj:
        return jsonify({"error": "项目不存在"}), 404
    data = request.get_json(silent=True) or {}
    pkg_dir = (data.get("package_dir") or request.form.get("package_dir") or "").strip()
    if not pkg_dir or not os.path.isdir(pkg_dir):
        return jsonify({"error": "请提供有效的 package_dir（已导出的打包文件夹绝对路径）"}), 400

    # 1) 提示词
    prompt_src = os.path.join(pkg_dir, "prompts")
    prompt_dst = _sub(proj_path, "prompt")
    os.makedirs(prompt_dst, exist_ok=True)
    imported_prompts, skipped_prompts = [], []
    if os.path.isdir(prompt_src):
        for f in sorted(os.listdir(prompt_src)):
            if not f.endswith(".json"):
                continue
            dst = os.path.join(prompt_dst, f)
            if os.path.exists(dst):
                skipped_prompts.append(f)
                continue
            shutil.copy2(os.path.join(prompt_src, f), dst)
            imported_prompts.append(f)

    # 2) 资产（图片/视频，按扩展名落位）
    img_dst = _sub(proj_path, "image")
    vid_dst = _sub(proj_path, "video")
    os.makedirs(img_dst, exist_ok=True)
    os.makedirs(vid_dst, exist_ok=True)
    IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
    VID_EXT = (".mp4", ".mov", ".webm")
    imported_assets, skipped_assets = [], []
    for f in sorted(os.listdir(pkg_dir)):
        low = f.lower()
        if low.endswith(IMG_EXT):
            dst = os.path.join(img_dst, f)
            if os.path.exists(dst):
                skipped_assets.append(f)
                continue
            shutil.copy2(os.path.join(pkg_dir, f), dst)
            imported_assets.append(f)
        elif low.endswith(VID_EXT):
            dst = os.path.join(vid_dst, f)
            if os.path.exists(dst):
                skipped_assets.append(f)
                continue
            shutil.copy2(os.path.join(pkg_dir, f), dst)
            imported_assets.append(f)

    if not imported_prompts and not imported_assets:
        return jsonify({
            "ok": True,
            "imported_prompts": [], "skipped_prompts": skipped_prompts,
            "imported_assets": [], "skipped_assets": skipped_assets,
            "message": "打包文件夹中未发现可导入的提示词或资产文件（可能为空或内容已存在）。",
        })

    return jsonify({
        "ok": True,
        "imported_prompts": imported_prompts,
        "skipped_prompts": skipped_prompts,
        "imported_assets": imported_assets,
        "skipped_assets": skipped_assets,
        "message": (
            f"已导入 {len(imported_prompts)} 个提示词、{len(imported_assets)} 个资产；"
            f"跳过已存在 {len(skipped_prompts) + len(skipped_assets)} 个。"
        ),
    })


def _register_version(project_id, asset_type, asset_key, content, as_final, notes, content_hash=None):
    """把一个导入内容登记为 asset_versions 的一个版本（可选最终版）。

    - content_hash 由调用方提供（素材=图片字节哈希，提示词=JSON 文本哈希），用于跨「文件名碰撞改名」的
      稳定去重：同一份外部文件无论导入几次都命中同一版本，不会因 _1/_2 改名而产生重复最终版。
    - as_final=True 时：清除同资产其他最终版，再把本版本置为最终版。
    content 约定为「项目相对路径」（素材）或「提示词 JSON 文本」（分镜提示词）。
    """
    from web.models.asset_models import AssetVersion
    if content_hash is None:
        content_hash = hashlib.md5((content or "").encode()).hexdigest()[:12]
    latest = AssetVersion.query.filter_by(
        project_id=project_id, asset_type=asset_type, asset_key=asset_key
    ).order_by(AssetVersion.created_time.desc()).first()

    if latest and latest.content_hash == content_hash:
        if as_final:
            AssetVersion.query.filter_by(
                project_id=project_id, asset_type=asset_type, asset_key=asset_key, is_final=True
            ).update({"is_final": False})
            latest.is_final = True
        if notes:
            latest.notes = notes
        db.session.commit()
        return latest

    if latest and latest.version_tag.startswith("v"):
        try:
            n = int(latest.version_tag[1:]) + 1
            tag = f"v{n}"
        except ValueError:
            tag = "v1"
    else:
        tag = "v1"

    if as_final:
        AssetVersion.query.filter_by(
            project_id=project_id, asset_type=asset_type, asset_key=asset_key, is_final=True
        ).update({"is_final": False})

    v = AssetVersion(
        project_id=project_id, asset_type=asset_type, asset_key=asset_key,
        version_tag=tag, content=content, content_hash=content_hash,
        notes=notes or ("外部导入" + ("·最终版" if as_final else "")),
        is_final=as_final,
    )
    db.session.add(v)
    db.session.commit()
    return v


@bp.route("/<int:project_id>/import-external", methods=["POST"])
def import_external(project_id):
    """一步导入外部文件，并可登记为「最终版」。

    适用两种素材来源：
      - kind=asset   外部图片 → 存 08_Image，并登记 asset_versions（asset_type 默认 reference）
      - kind=prompt  外部分镜提示词 JSON → 存 07_Prompt，并登记 asset_versions(asset_type=storyboard_prompt)

    Form 字段：
      file       必填，外部文件
      kind       必填，"asset" | "prompt"
      asset_key  可选，资产/镜头标识（默认取文件名主干）
      asset_type 可选（仅 asset），默认 "reference"
      as_final   可选，"true"/"1"/"yes" 表示登记为最终版（自动清除同资产其他最终版）
      notes      可选，版本备注

    去重：素材按图片字节哈希、提示词按 JSON 文本哈希；同一份外部文件重复导入只复用/刷新既有版本，
    不生成重复最终版，也不留下改名孤儿文件。返回落盘路径 + 是否最终版。
    """
    proj, proj_path = _proj_path(project_id)
    if not proj:
        return jsonify({"error": "项目不存在"}), 404
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "缺少文件"}), 400
    kind = (request.form.get("kind") or "").strip().lower()
    if kind not in ("asset", "prompt"):
        return jsonify({"error": "kind 必须是 asset 或 prompt"}), 400

    raw_name = (request.form.get("asset_key") or os.path.splitext(file.filename)[0] or "imported").strip()
    asset_key = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", raw_name)[:120]
    as_final = str(request.form.get("as_final", "")).strip().lower() in ("1", "true", "yes")
    notes = (request.form.get("notes") or "").strip()

    if kind == "asset":
        ext = os.path.splitext(file.filename)[1].lower() or ".png"
        if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
            ext = ".png"
        try:
            fb = file.read()
        except Exception as e:
            return jsonify({"error": f"读取文件失败：{e}"}), 400
        fb_hash = hashlib.md5(fb).hexdigest()[:12]

        from web.models.asset_models import AssetVersion
        latest = AssetVersion.query.filter_by(
            project_id=project_id, asset_type="reference", asset_key=asset_key
        ).order_by(AssetVersion.created_time.desc()).first()
        if latest and latest.content_hash == fb_hash:
            # 同内容：就地刷新最终版标记，不重写文件、不新建版本（幂等）
            if as_final:
                AssetVersion.query.filter_by(
                    project_id=project_id, asset_type="reference", asset_key=asset_key, is_final=True
                ).update({"is_final": False})
                latest.is_final = True
            if notes:
                latest.notes = notes
            db.session.commit()
            rel = latest.content
            dst = os.path.join(proj_path, rel.replace("/", os.sep))
            return jsonify({
                "ok": True, "kind": "asset", "filename": os.path.basename(dst),
                "path": dst, "rel": rel, "is_final": as_final, "reused": True,
                "message": f"已复用既有素材版本：{os.path.basename(dst)}"
                           + ("（已刷新为最终版）" if as_final else ""),
            })

        image_dir = _sub(proj_path, "image")
        os.makedirs(image_dir, exist_ok=True)
        dst = os.path.join(image_dir, asset_key + ext)
        if os.path.exists(dst):
            base, e = os.path.splitext(dst)
            i = 1
            while os.path.exists(f"{base}_{i}{e}"):
                i += 1
            dst = f"{base}_{i}{e}"
        with open(dst, "wb") as f:
            f.write(fb)
        rel = os.path.relpath(dst, proj_path).replace(os.sep, "/")
        asset_type = (request.form.get("asset_type") or "reference").strip() or "reference"
        _register_version(project_id, asset_type, asset_key, rel, as_final, notes, content_hash=fb_hash)
        return jsonify({
            "ok": True, "kind": "asset", "filename": os.path.basename(dst),
            "path": dst, "rel": rel, "is_final": as_final,
            "message": f"已导入素材：{os.path.basename(dst)}"
                       + ("（已标记最终版）" if as_final else ""),
        })

    # kind == "prompt"
    try:
        raw = file.read().decode("utf-8", "ignore")
        data = json.loads(raw)
    except Exception as e:
        return jsonify({"error": f"提示词文件不是合法 JSON：{e}"}), 400
    if not isinstance(data, dict):
        return jsonify({"error": "分镜提示词 JSON 必须是对象"}), 400
    text_hash = hashlib.md5(raw.encode("utf-8", "ignore")).hexdigest()[:12]

    from web.models.asset_models import AssetVersion
    latest = AssetVersion.query.filter_by(
        project_id=project_id, asset_type="storyboard_prompt", asset_key=asset_key
    ).order_by(AssetVersion.created_time.desc()).first()
    if latest and latest.content_hash == text_hash:
        if as_final:
            AssetVersion.query.filter_by(
                project_id=project_id, asset_type="storyboard_prompt", asset_key=asset_key, is_final=True
            ).update({"is_final": False})
            latest.is_final = True
        if notes:
            latest.notes = notes
        db.session.commit()
        rel = latest.content
        dst = os.path.join(proj_path, rel.replace("/", os.sep))
        return jsonify({
            "ok": True, "kind": "prompt", "filename": os.path.basename(dst),
            "path": dst, "rel": rel, "is_final": as_final, "reused": True,
            "message": f"已复用既有的分镜提示词版本：{os.path.basename(dst)}"
                       + ("（已刷新为最终版）" if as_final else ""),
        })

    prompt_dir = _sub(proj_path, "prompt")
    os.makedirs(prompt_dir, exist_ok=True)
    dst = os.path.join(prompt_dir, asset_key + ".json")
    if os.path.exists(dst):
        base, e = os.path.splitext(dst)
        i = 1
        while os.path.exists(f"{base}_{i}{e}"):
            i += 1
        dst = f"{base}_{i}{e}"
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    rel = os.path.relpath(dst, proj_path).replace(os.sep, "/")
    _register_version(project_id, "storyboard_prompt", asset_key, raw, as_final, notes, content_hash=text_hash)
    return jsonify({
        "ok": True, "kind": "prompt", "filename": os.path.basename(dst),
        "path": dst, "rel": rel, "is_final": as_final,
        "message": f"已导入分镜提示词：{os.path.basename(dst)}"
                   + ("（已标记最终版）" if as_final else ""),
    })
