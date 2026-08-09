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
from web.models.database import db, ProjectModel

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
            "three_view_status": (c.three_view_status or "") if c else "",
        })

    # 场景库交叉校验
    from web.models.novel_models import SceneLibrary
    scene_lib = {s.name: s for s in SceneLibrary.query.filter_by(project_id=project_id).all()}
    locations = []
    for loc, info in sorted(loc_index.items(), key=lambda x: -x[1]["count"]):
        s = scene_lib.get(loc)
        locations.append({
            "name": loc,
            "shot_count": info["count"],
            "shots": info["shots"],
            "in_library": s is not None,
            "four_angle_status": (s.four_angle_status or "") if s else "",
        })

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


def _ensure_default_world(project_id):
    """确保项目有一个世界观记录（实体建档需要 world_id 外键）；返回 world.id。"""
    from web.models.novel_models import WorldSetting
    world = WorldSetting.query.filter_by(project_id=project_id).first()
    if not world:
        world = WorldSetting(project_id=project_id, name="默认世界观")
        db.session.add(world)
        db.session.commit()
    return world.id


def _is_generic_name(name):
    """跳过「群演/路人/旁白」等占位名，避免污染角色库。"""
    import re
    return bool(re.fullmatch(r"群演\d*|路人[甲乙丙丁]?|旁白|画外音|系统|无", name.strip()))


@bp.route("/<int:project_id>/import", methods=["POST"])
def import_entities(project_id):
    """把实体图谱里派生出的角色 / 场景地点批量建档进库（不调用 LLM，零成本）。

    - 角色写入 novel_characters（出现最多的标记为「主角」），并置 three_view_status=pending，便于后续一键生成三视图；
    - 场景写入 scene_library，置 four_angle_status=pending，便于后续一键生成四角度。
    已存在的按 name 去重，不会重复建档。
    """
    from web.models.novel_models import NovelCharacter, SceneLibrary
    proj = ProjectModel.query.get_or_404(project_id)
    shots = _scan_scripts(current_app.config["ROOT_PATH"], proj.name)

    char_index = {}
    loc_index = {}
    for sh in shots:
        for name in sh["characters"]:
            char_index[name] = char_index.get(name, 0) + 1
        if sh["location"]:
            loc_index[sh["location"]] = loc_index.get(sh["location"], 0) + 1

    world_id = _ensure_default_world(project_id)

    created_chars, skipped_chars = [], []
    for name, cnt in char_index.items():
        if _is_generic_name(name):
            skipped_chars.append(name)
            continue
        exist = NovelCharacter.query.filter_by(project_id=project_id, name=name).first()
        if exist:
            skipped_chars.append(name)
            continue
        role = "主角" if cnt == max(char_index.values()) else "配角"
        c = NovelCharacter(
            project_id=project_id, world_id=world_id, name=name, role=role,
            appearance="", three_view_status="pending",
        )
        db.session.add(c)
        created_chars.append(name)

    created_scenes, skipped_scenes = [], []
    for name in loc_index:
        exist = SceneLibrary.query.filter_by(project_id=project_id, name=name).first()
        if exist:
            skipped_scenes.append(name)
            continue
        s = SceneLibrary(project_id=project_id, name=name, four_angle_status="pending")
        db.session.add(s)
        created_scenes.append(name)

    db.session.commit()
    return jsonify({
        "ok": True,
        "created_characters": created_chars,
        "skipped_characters": skipped_chars,
        "created_scenes": created_scenes,
        "skipped_scenes": skipped_scenes,
    })


@bp.route("/<int:project_id>/scene-library", methods=["GET"])
def list_scene_library(project_id):
    from web.models.novel_models import SceneLibrary
    rows = SceneLibrary.query.filter_by(project_id=project_id).order_by(SceneLibrary.name).all()
    return jsonify([s.to_dict() for s in rows])


@bp.route("/<int:project_id>/generate-three-view", methods=["POST"])
def generate_three_view(project_id):
    """为角色库批量生成 前/侧/后 三视图设定（调用 LLM，仅耗 token）。mock=1 时用模板占位（离线/免额度）。"""
    from web.models.novel_models import NovelCharacter
    data = request.get_json(silent=True) or {}
    force = bool(data.get("force", False))
    mock = bool(data.get("mock", False))
    chars = NovelCharacter.query.filter_by(project_id=project_id).all()
    done, errors = [], []
    for c in chars:
        if (not force) and c.three_view_status == "done" and (c.three_view_prompt or "").strip():
            continue
        c.three_view_status = "generating"
        db.session.commit()
        try:
            if mock:
                tv = {
                    "front": f"【{c.name}·正面】标准站姿，清晰展现五官与标志性服饰，详见角色设定。",
                    "side": f"【{c.name}·侧面】45°侧身，体现身材比例与轮廓剪影。",
                    "back": f"【{c.name}·背面】展示背面特征与随身物件（背包/武器等）。",
                }
            else:
                from web.services.novel_ai_service import generate_character_three_view
                world_ctx = ""
                try:
                    w = c.world
                    world_ctx = (w.ai_context or w.notes or "") if w else ""
                except Exception:
                    pass
                tv = generate_character_three_view(
                    {"name": c.name, "role": c.role, "appearance": c.appearance,
                     "visual_prompt": c.visual_prompt, "world_context": world_ctx},
                    project_id=project_id,
                )
            c.three_view_prompt = json.dumps(tv, ensure_ascii=False)
            c.three_view_status = "done"
            db.session.commit()
            done.append(c.name)
        except Exception as e:
            c.three_view_status = "error"
            db.session.commit()
            errors.append({"name": c.name, "error": str(e)[:200]})
    return jsonify({"ok": True, "generated": done, "errors": errors})


@bp.route("/<int:project_id>/generate-four-angle", methods=["POST"])
def generate_four_angle(project_id):
    """为场景库批量生成 正/反/侧/俯 四角度设定（调用 LLM，仅耗 token）。mock=1 时用模板占位（离线/免额度）。"""
    from web.models.novel_models import SceneLibrary
    data = request.get_json(silent=True) or {}
    force = bool(data.get("force", False))
    mock = bool(data.get("mock", False))
    scenes = SceneLibrary.query.filter_by(project_id=project_id).all()
    done, errors = [], []
    for s in scenes:
        if (not force) and s.four_angle_status == "done" and (s.angle_front or s.angle_back):
            continue
        s.four_angle_status = "generating"
        db.session.commit()
        try:
            if mock:
                fa = {
                    "front": f"【{s.name}·正打】主视角呈现空间关系与核心物件，光线与色调统一。",
                    "back": f"【{s.name}·反打】越过主体回望，交代环境纵深。",
                    "side": f"【{s.name}·侧打】横向机位展示场景横向构成。",
                    "over": f"【{s.name}·俯拍】高位俯视交代整体布局。",
                }
            else:
                from web.services.novel_ai_service import generate_scene_four_angle
                fa = generate_scene_four_angle(
                    {"name": s.name, "description": s.description, "mood": ""},
                    project_id=project_id,
                )
            s.angle_front = fa.get("front", "")
            s.angle_back = fa.get("back", "")
            s.angle_side = fa.get("side", "")
            s.angle_over = fa.get("over", "")
            # 主视觉锚：以正打为主，拼接四角度要点，供分镜提示词场景一致性注入
            s.visual_prompt = "；".join([v for v in fa.values() if v and v.strip()])
            s.four_angle_status = "done"
            db.session.commit()
            done.append(s.name)
        except Exception as e:
            s.four_angle_status = "error"
            db.session.commit()
            errors.append({"name": s.name, "error": str(e)[:200]})
    return jsonify({"ok": True, "generated": done, "errors": errors})


@bp.route("/<int:project_id>/apply-angles", methods=["POST"])
def apply_angles_to_prompts(project_id):
    """把场景库主视觉锚（visual_prompt）幂等注入 07_Prompt 每条分镜（【场景设定·地点】标签）。

    不重跑 LLM：仅把已生成的场景四角度 anchor 写回分镜提示词，使其真正「接进提示词」。
    """
    from web.models.novel_models import SceneLibrary
    proj = ProjectModel.query.get_or_404(project_id)
    proj_dir = os.path.join(current_app.config["ROOT_PATH"], "02_Projects", proj.name)
    prompt_dir = os.path.join(proj_dir, "07_Prompt")
    scenes = {s.name: s for s in SceneLibrary.query.filter_by(project_id=project_id).all()}
    if not os.path.isdir(prompt_dir):
        return jsonify({"ok": False, "error": "未找到 07_Prompt 目录"})

    applied = 0
    for f in sorted(os.listdir(prompt_dir)):
        if not f.endswith(".json"):
            continue
        path = os.path.join(prompt_dir, f)
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        loc = (d.get("location") or "").strip()
        sc = scenes.get(loc)
        if not sc or not (sc.visual_prompt or "").strip():
            continue
        vp = d.get("video_prompt", "")
        tag = f"【场景设定·{loc}】{sc.visual_prompt}"
        # 幂等：先移除旧的同地点场景锚，再追加
        vp = _strip_angle_tag(vp, loc)
        vp = (vp + "\n\n" + tag) if vp.strip() else tag
        d["video_prompt"] = vp
        d["scene_anchor"] = sc.visual_prompt
        json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        applied += 1
    return jsonify({"ok": True, "applied": applied})


def _strip_angle_tag(vp, loc):
    """移除 video_prompt 中已有的【场景设定·loc】整段（含其后空行）。"""
    import re
    return re.sub(rf"\n*【场景设定·{re.escape(loc)}】.*?(\n\n|$)", "", vp, flags=re.S).strip()
