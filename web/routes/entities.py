"""实体派生 API - 从剧本自动抽取角色 / 场景地点，并做互链与角色库交叉校验

让「实体图谱」面板可以：
  · 看到剧本里出现过的每个角色、TA 出现在哪些分镜（反查）
  · 看到每个场景地点覆盖了哪些分镜
  · 标出「剧本里有、但角色库还没有」的未知角色，便于一键归入角色库
  · 显示哪些角色已开启一致性锁（防变脸）
"""
import os
import re
import json

from flask import Blueprint, jsonify, request, current_app

bp = Blueprint("entities", __name__)


def _shot_label(shot):
    sid = shot.get("shot_id")
    return f"S{sid:02d}" if isinstance(sid, int) else f"#{sid}"


def _scan_scripts(root_path, project_name):
    """扫描 05_Script 与 07_Prompt，按分镜号合并出每个分镜的角色与地点。

    以 07_Prompt（生产级逐镜数据，分镜画布也读它）为主，05_Script 补充地点等信息，
    避免「实体图谱镜头数」与「分镜画布」因剧本被重新生成而出现不一致。
    """
    proj_dir = os.path.join(root_path, "02_Projects", project_name)
    shots = {}  # shot_label -> {"characters": set, "location": str}

    def ensure(label):
        return shots.setdefault(label, {"characters": set(), "location": ""})

    # 1) 优先从 07_Prompt 取逐镜角色（已含 characters 字段）
    prompt_dir = os.path.join(proj_dir, "07_Prompt")
    if os.path.isdir(prompt_dir):
        for f in sorted(os.listdir(prompt_dir)):
            if not f.endswith(".json"):
                continue
            try:
                with open(os.path.join(prompt_dir, f), "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                continue
            m = re.search(r"_S(\d+)", f)
            label = f"S{int(m.group(1)):02d}" if m else (data.get("shot_label") or f)
            entry = ensure(label)
            for c in data.get("characters", []) or []:
                if isinstance(c, str) and c.strip():
                    entry["characters"].add(c)
                elif isinstance(c, dict) and c.get("name"):
                    entry["characters"].add(c["name"])

    # 2) 从 05_Script 补充角色与地点
    script_dir = os.path.join(proj_dir, "05_Script")
    if os.path.isdir(script_dir):
        for f in sorted(os.listdir(script_dir)):
            if not f.endswith(".json"):
                continue
            try:
                with open(os.path.join(script_dir, f), "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                continue
            for sh in data.get("shots", []):
                label = _shot_label(sh)
                entry = ensure(label)
                for c in sh.get("characters", []) or []:
                    if isinstance(c, dict) and c.get("name"):
                        entry["characters"].add(c["name"])
                    elif isinstance(c, str) and c.strip():
                        entry["characters"].add(c)
                loc = (sh.get("location") or "").strip()
                if loc:
                    entry["location"] = loc

    return [
        {"shot_label": k, "characters": sorted(v["characters"]), "location": v["location"]}
        for k, v in sorted(shots.items())
    ]


@bp.route("/<int:project_id>", methods=["GET"])
def get_entities(project_id):
    from web.models.database import ProjectModel
    from web.models.novel_models import NovelCharacter

    proj = ProjectModel.query.get_or_404(project_id)
    project_name = proj.name
    root_path = current_app.config["ROOT_PATH"]

    shots = _scan_scripts(root_path, project_name)

    # 角色聚合
    char_index = {}        # name -> {count, shots:[]}
    loc_index = {}         # location -> {count, shots:[]}
    for sh in shots:
        for name in sh["characters"]:
            if name not in char_index:
                char_index[name] = {"count": 0, "shots": []}
            char_index[name]["count"] += 1
            char_index[name]["shots"].append(sh["shot_label"])
        loc = sh["location"]
        if loc:
            if loc not in loc_index:
                loc_index[loc] = {"count": 0, "shots": []}
            loc_index[loc]["count"] += 1
            loc_index[loc]["shots"].append(sh["shot_label"])

    # 交叉校验角色库
    known = {c.name: c for c in NovelCharacter.query.filter_by(project_id=project_id).all()}
    characters = []
    for name, info in sorted(char_index.items(), key=lambda x: -x[1]["count"]):
        c = known.get(name)
        characters.append({
            "name": name,
            "id": c.id if c else None,
            "shot_count": info["count"],
            "shots": info["shots"],
            "in_library": c is not None,
            "role": c.role if c else "",
            "appearance": (c.appearance or "") if c else "",
            "locked": bool(c.consistency_lock) if c else False,
            "locked_prompt": (c.locked_prompt or "") if c else "",
        })

    locations = [
        {"name": loc, "shot_count": info["count"], "shots": info["shots"]}
        for loc, info in sorted(loc_index.items(), key=lambda x: -x[1]["count"])
    ]

    # 未知角色：剧本出现但角色库没有
    unknown = [c["name"] for c in characters if not c["in_library"]]

    return jsonify({
        "project_id": project_id,
        "project_name": project_name,
        "total_shots": len(shots),
        "characters": characters,
        "locations": locations,
        "unknown_characters": unknown,
        "locked_count": sum(1 for c in characters if c["locked"]),
    })
