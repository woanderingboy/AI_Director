"""素材打包 API - 从分镜提取需求，匹配资产库，打包导出

设计目标（对照需求）：
1. 适配任何场景：可打包的素材 = 08_Image / 09_Video 中的真实文件，按文件名分组，
   即使一个只有图片的文件夹也能正常打包。
2. 没有素材明确提醒：文件夹完全为空 → 拦截并提示「确实没有任何素材」；分镜要求的角色/场景
   参考图缺失 → 醒目「确实缺失」提醒（不阻断其他素材打包，建议到资产管理补充）。
3. 多版本素材让你确认最终版：同一资产出现多个候选文件（不同渲染/导入版本）时标记为「需确认」，
   必须由用户单选最终版后才打包该文件。
"""
import os
import re
import json
import shutil
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
from web.models.database import db
from web.models.asset_models import AssetPackage

bp = Blueprint("asset_packages", __name__)

PROJECT_IMG_DIR = "08_Image"
PROJECT_VID_DIR = "09_Video"
PROMPT_DIR = "07_Prompt"


def _norm(s):
    """归一化用于文件名匹配：保留中日韩/字母/数字，去掉空白与标点。"""
    if not s:
        return ""
    out = []
    for ch in str(s).lower():
        if ch.isalnum() or "一" <= ch <= "鿿":
            out.append(ch)
    return "".join(out)


_VERSION_RE = re.compile(r"[_－-]?(v\d+|final|最终版|备选|副本\d*|版\d*)$", re.I)
_TRAIL_NUM_RE = re.compile(r"_\d+$")


def _group_key(base):
    """从文件名去掉末尾版本标记，得到「同一资产」的分组键。"""
    b = _VERSION_RE.sub("", base)
    b = _TRAIL_NUM_RE.sub("", b)
    return b.strip() or base


def _pid_by_name(project_name):
    from web.models.database import ProjectModel
    p = ProjectModel.query.filter_by(name=project_name).first()
    return p.id if p else None


def _load_shots(root_path, project_name):
    """从 07_Prompt 读取分镜；无则回退 NovelScene；再无返回 []。"""
    shots = []
    prompt_dir = os.path.join(root_path, "02_Projects", project_name, PROMPT_DIR)
    if os.path.isdir(prompt_dir):
        for f in sorted(x for x in os.listdir(prompt_dir) if x.endswith(".json")):
            try:
                with open(os.path.join(prompt_dir, f), "r", encoding="utf-8") as fh:
                    d = json.load(fh)
                shots.append({
                    "shot_id": d.get("shot_id"),
                    "characters": d.get("characters") or [],
                    "location": (d.get("location") or "").strip(),
                    "video_prompt": d.get("video_prompt") or "",
                })
            except Exception:
                continue
    if shots:
        return shots
    try:
        from web.models.novel_models import NovelScene
        pid = _pid_by_name(project_name)
        for s in NovelScene.query.filter_by(project_id=pid).all():
            loc = getattr(s, "location", "") or ""
            shots.append({
                "shot_id": getattr(s, "order", None) or s.id,
                "characters": [],
                "location": loc if isinstance(loc, str) else "",
                "video_prompt": s.summary or "",
            })
    except Exception:
        pass
    return shots


def _required_names(shots):
    chars, scenes = set(), set()
    for shot in shots:
        for c in (shot.get("characters") or []):
            if c:
                chars.add(c)
        loc = (shot.get("location") or "").strip()
        if loc:
            scenes.add(loc)
    return chars, scenes


def _analyze(project_id, prompt_text=""):
    from web.models.database import ProjectModel
    proj = ProjectModel.query.get(project_id)
    project_name = proj.name if proj else None
    root_path = current_app.config["ROOT_PATH"]

    # 1) 收集可打包文件并按分组键归组（识别多版本）
    groups = {}
    proj_root = os.path.join(root_path, "02_Projects", project_name) if project_name else None

    def add_file(fpath, source, atype):
        f = os.path.basename(fpath)
        gk = _group_key(os.path.splitext(f)[0])
        g = groups.setdefault(gk, {"type": atype, "files": []})
        g["files"].append({"file": f, "source": source, "path": fpath})

    if proj_root:
        for sub, atype in ((PROJECT_IMG_DIR, "image"), (PROJECT_VID_DIR, "video")):
            d = os.path.join(proj_root, sub)
            if os.path.isdir(d):
                for f in sorted(os.listdir(d)):
                    if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov")):
                        add_file(os.path.join(d, f), "project", atype)

    # 2) 需求侧：分镜要求的角色/场景参考图是否缺失（仅提醒，不阻断）
    shots = _load_shots(root_path, project_name) if project_name else []
    req_chars, req_scenes = _required_names(shots)
    all_names_norm = {_norm(f["file"]) for g in groups.values() for f in g["files"]}
    missing_ref = []
    for name in sorted(req_chars | req_scenes):
        n = _norm(name)
        if n and not any(n in fn for fn in all_names_norm):
            missing_ref.append(name)

    # 3) 构建资产列表
    assets = []
    for gk, g in groups.items():
        cands = g["files"]
        if len(cands) == 1:
            status, final = "ok", cands[0]["file"]
        else:
            status, final = "need_confirm", None
        assets.append({
            "asset_key": f"filegroup:{gk}",
            "type": g["type"],
            "optional": False,
            "required_by": [],
            "search_names": [gk],
            "candidates": cands,
            "status": status,
            "final_file": final,
        })
    # 缺失参考图（提醒型）
    for name in missing_ref:
        assets.append({
            "asset_key": f"ref:{name}",
            "type": "ref_missing",
            "optional": True,
            "required_by": [],
            "search_names": [name],
            "candidates": [],
            "status": "missing",
            "final_file": None,
        })

    has_files = len(groups) > 0
    # 全局素材图例（角色/场景按分镜出现顺序编号），供前端预览与导出重命名共用
    try:
        from web.services.storyboard_assets import build_legend_from_shots
        _legend, _ = build_legend_from_shots(shots)
    except Exception:
        _legend = []
    return {
        "project_name": project_name,
        "legend": _legend,
        "shots": [{"shot_id": s.get("shot_id"), "characters": s.get("characters"),
                   "location": s.get("location")} for s in shots],
        "assets": assets,
        "missing_count": 0 if has_files else 1,   # 0 文件才是硬性缺失
        "missing_ref_count": len(missing_ref),
        "need_confirm_count": sum(1 for a in assets if a["status"] == "need_confirm"),
        "matched_auto_count": sum(1 for a in assets if a["status"] == "ok"),
        "total_files": sum(len(g["files"]) for g in groups.values()),
    }


@bp.route("/<int:project_id>/analyze", methods=["POST"])
def analyze_requirements(project_id):
    """分析分镜与素材，返回分组后的打包资产与缺失/需确认提示。"""
    data = request.get_json() or {}
    return jsonify(_analyze(project_id, data.get("prompt_text", "")))


@bp.route("/<int:project_id>/create", methods=["POST"])
def create_package(project_id):
    """创建素材打包（可携带 selection 指定各资产最终版）。"""
    data = request.get_json() or {}
    name = data.get("name", f"素材包_{datetime.now().strftime('%m%d_%H%M')}")
    selection = data.get("selection") or {}

    result = _analyze(project_id)
    assets = result["assets"]
    for a in assets:
        if a["asset_key"] in selection:
            chosen = selection[a["asset_key"]]
            if any(c["file"] == chosen for c in a.get("candidates", [])):
                a["final_file"] = chosen
                if a["status"] == "need_confirm":
                    a["status"] = "ok"
        if a["status"] == "missing":
            a["final_file"] = None

    unconfirmed = [a for a in assets if a["status"] == "need_confirm" and not a.get("final_file")]
    status = "draft" if unconfirmed else "ready"

    pkg = AssetPackage(
        project_id=project_id,
        name=name,
        description=data.get("description", ""),
        required_assets=json.dumps([{"asset_key": a["asset_key"], "type": a["type"]} for a in assets], ensure_ascii=False),
        matched_assets=json.dumps(assets, ensure_ascii=False, default=str),
        missing_assets=json.dumps(result["missing_ref_count"], ensure_ascii=False),
        status=status,
    )
    db.session.add(pkg)
    db.session.commit()
    return jsonify(pkg.to_dict()), 201


@bp.route("/<int:project_id>/packages", methods=["GET"])
def list_packages(project_id):
    packages = AssetPackage.query.filter_by(project_id=project_id).order_by(AssetPackage.created_time.desc()).all()
    return jsonify([p.to_dict() for p in packages])


@bp.route("/packages/<int:pkg_id>", methods=["GET"])
def get_package(pkg_id):
    return jsonify(AssetPackage.query.get_or_404(pkg_id).to_dict())


@bp.route("/packages/<int:pkg_id>", methods=["DELETE"])
def delete_package(pkg_id):
    pkg = AssetPackage.query.get_or_404(pkg_id)
    db.session.delete(pkg)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/packages/<int:pkg_id>/export", methods=["POST"])
def export_package(pkg_id):
    """导出素材包：仅导出最终确认版；多版本未确认或无素材则明确拦截。"""
    pkg = AssetPackage.query.get_or_404(pkg_id)
    root_path = current_app.config["ROOT_PATH"]
    from web.models.database import ProjectModel
    proj = ProjectModel.query.get(pkg.project_id)
    project_name = proj.name if proj else None
    data = request.get_json() or {}
    selection = data.get("selection") or {}

    assets = json.loads(pkg.matched_assets) if pkg.matched_assets else []
    for a in assets:
        if a["asset_key"] in selection:
            chosen = selection[a["asset_key"]]
            if any(c["file"] == chosen for c in a.get("candidates", [])):
                a["final_file"] = chosen
                if a["status"] == "need_confirm":
                    a["status"] = "ok"

    unconfirmed = [a for a in assets if a["status"] == "need_confirm" and not a.get("final_file")]

    if unconfirmed:
        return jsonify({
            "ok": False,
            "blocked": True,
            "unconfirmed": [a["asset_key"] for a in unconfirmed],
            "error": "以下素材存在多个版本，请先确认最终版再导出。",
        }), 409

    export_dir = data.get("export_dir", os.path.join(root_path, "04_Output", f"package_{pkg.id}"))
    os.makedirs(export_dir, exist_ok=True)

    # 全局素材图例：按分镜出现顺序排列角色/场景，导出文件名 01/02… 与之对应
    try:
        from web.services.storyboard_assets import build_asset_legend
        _legend, _ = build_asset_legend(root_path, project_name)
    except Exception:
        _legend = []
    _legend_idx_by_name = {_norm(e["name"]): e["index"] for e in _legend}
    _legend_kind = {e["index"]: e["kind"] for e in _legend}
    _legend_name = {e["index"]: e["name"] for e in _legend}

    # 为每条资产分配图号：图例命中的用图例编号，其余顺延填充
    _target = {}        # asset_key -> 图号
    _used_idx = set()
    _max_legend = max([e["index"] for e in _legend], default=0)
    _next_free = 1
    for a in assets:
        gk = a["asset_key"].split(":", 1)[-1]   # filegroup:xxx / ref:xxx
        gi = _legend_idx_by_name.get(_norm(gk))
        if gi and gi not in _used_idx:
            _target[a["asset_key"]] = gi
            _used_idx.add(gi)
    for a in assets:
        if a["asset_key"] in _target:
            continue
        while _next_free <= _max_legend or _next_free in _used_idx:
            _next_free += 1
        _target[a["asset_key"]] = _next_free
        _used_idx.add(_next_free)
        _next_free += 1

    # 按图号排序后导出，命名为 01.jpg / 02.jpg …（不做自动关联，纯按图例顺序重命名）
    _ordered = sorted(assets, key=lambda a: _target.get(a["asset_key"], 10 ** 9))
    exported, errors, used = [], [], []
    for a in _ordered:
        if a.get("optional") and a["status"] == "missing":
            continue
        final = a.get("final_file")
        if not final:
            continue
        cand = next((c for c in a.get("candidates", []) if c["file"] == final), None)
        if not cand or not os.path.exists(cand["path"]):
            errors.append(f"最终版文件不存在: {final}")
            continue
        ext = os.path.splitext(cand["path"])[1]
        gi = _target[a["asset_key"]]
        dst_name = f"{gi:02d}{ext}"
        dst = os.path.join(export_dir, dst_name)
        if os.path.exists(dst):
            dst = os.path.join(export_dir, f"{gi:02d}_{len(exported)}{ext}")
        try:
            shutil.copy2(cand["path"], dst)
            exported.append(dst)
            used.append({
                "asset_key": a["asset_key"],
                "file": os.path.basename(dst),
                "fig": f"图{gi}",
                "kind": _legend_kind.get(gi, ""),
                "name": _legend_name.get(gi, ""),
            })
        except Exception as e:
            errors.append(f"复制失败 {final}: {e}")

    if not exported:
        return jsonify({
            "ok": False,
            "error": "确实没有任何可导出的素材文件。请先将资产图/视频放入 02_Projects/{项目名}/08_Image/ 或 09_Video/ 目录。",
            "exported_count": 0,
            "exported": [],
            "errors": errors,
        }), 400

    # index.json
    index_data = {
        "project": project_name or "unknown",
        "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "legend": _legend,
        "asset_map": {u["file"]: {k: u[k] for k in ("file", "fig", "kind", "name", "asset_key")} for u in used},
        "shots": [],
        "assets": used,
    }
    prompt_dir = os.path.join(root_path, "02_Projects", project_name or "", PROMPT_DIR)
    if os.path.isdir(prompt_dir):
        for pf in sorted(os.listdir(prompt_dir)):
            if pf.endswith(".json"):
                try:
                    with open(os.path.join(prompt_dir, pf), "r", encoding="utf-8") as f:
                        pdata = json.load(f)
                    index_data["shots"].append({
                        "file": pf,
                        "video_prompt": pdata.get("video_prompt", ""),
                        "camera": pdata.get("camera", ""),
                        "duration": pdata.get("duration", ""),
                    })
                except Exception:
                    pass

    index_path = os.path.join(export_dir, "index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)
    exported.append(index_path)

    if os.path.isdir(prompt_dir):
        prompt_export = os.path.join(export_dir, "prompts")
        os.makedirs(prompt_export, exist_ok=True)
        for pf in os.listdir(prompt_dir):
            if pf.endswith(".json"):
                shutil.copy2(os.path.join(prompt_dir, pf), os.path.join(prompt_export, pf))
                exported.append(os.path.join(prompt_export, pf))

    pkg.export_path = export_dir
    pkg.status = "packed"
    db.session.commit()

    return jsonify({
        "ok": True,
        "export_dir": export_dir,
        "exported_count": len(exported),
        "exported": exported,
        "errors": errors,
        "index": index_data,
    })


@bp.route("/naming-preview", methods=["POST"])
def naming_preview():
    data = request.get_json() or {}
    return jsonify({"normalized": _norm(data.get("name", "unnamed"))})
