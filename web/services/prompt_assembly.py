"""分镜提示词重组：把零散字段拼成最终交付格式。

最终格式（用户约定）：
  【素材参考】图1=林一野(角色图)；图5=塌陷烂尾楼(场景图)

  【项目设定】
  - 画风：…
  - 色调：…
  - 光线：…
  - 氛围：…
  - 渲染与质感：…（整体 positive_prompts）
  - 人物音色：林一野=低沉沙哑男声…（按本镜出场角色取）

  <镜头描述 / 动作 / 一致性锁 JSON>

  【负面】低质量,模糊,…（本镜 negative + 项目 negative）
"""
import re


def _split_legend(video_prompt):
    """把 video_prompt 拆成 (legend_text, scene_text)。"""
    lines = (video_prompt or "").split("\n")
    legend = []
    scene = []
    for ln in lines:
        if ln.strip().startswith("【素材参考】") or ln.strip().startswith("【场景设定"):
            legend.append(ln.strip())
        else:
            scene.append(ln)
    return "\n".join(legend).strip(), "\n".join(scene).strip("\n")


def _clean_scene(scene, gparts):
    """幂等清洗：剥离历史重跑累积的【项目设定】块（含其 bullet 行）与【负面】块，
    只保留真实镜头描述。这样 build_full_prompt 无论运行多少次都只输出一份。
    """
    gpart_set = set(gparts)
    # 首个【负面】之后的都为负面块，直接截断丢弃
    if "【负面】" in scene:
        scene = scene.split("【负面】", 1)[0]
    out = []
    for ln in scene.split("\n"):
        s = ln.strip()
        if s.startswith("【项目设定】"):
            continue
        if s in gpart_set:
            continue
        out.append(ln)
    return "\n".join(out).strip("\n")


def build_full_prompt(shot, g, characters=None):
    """拼接完整提示词。

    shot: dict(含 video_prompt, negative_prompt, characters, asset_refs)
    g: 项目全局设定 dict(art_style,color_palette,lighting,mood,positive_prompts,
                         negative_prompts,character_voices)
    characters: 本镜出场角色列表（缺省从 shot 取）
    """
    g = g or {}
    video_prompt = shot.get("video_prompt", "")
    legend, scene = _split_legend(video_prompt)

    # 项目设定段
    gparts = []
    if g.get("art_style"):
        gparts.append(f"- 画风：{g['art_style']}")
    if g.get("color_palette"):
        gparts.append(f"- 色调：{g['color_palette']}")
    if g.get("lighting"):
        gparts.append(f"- 光线：{g['lighting']}")
    if g.get("mood"):
        gparts.append(f"- 氛围：{g['mood']}")
    if g.get("positive_prompts"):
        gparts.append(f"- 渲染与质感：{g['positive_prompts']}")
    # 人物音色：仅取本镜出场角色
    chars = characters or shot.get("characters", []) or []
    voices = g.get("character_voices", {}) or {}
    cv = {c: voices[c] for c in chars if c in voices}
    if cv:
        gparts.append("- 人物音色：" + "；".join(f"{k}={v}" for k, v in cv.items()))
    gsec = "【项目设定】\n" + "\n".join(gparts) if gparts else ""

    # 幂等清洗：剥离 scene 中历史累积的项目设定/负面块，仅留真实镜头描述
    scene = _clean_scene(scene, gparts)

    # 负面段（去重：pipeline 已经把 g["negative_prompts"] 合并进 shot.negative_prompt）
    shot_neg = shot.get("negative_prompt", "") or ""
    g_neg = g.get("negative_prompts", "") or ""
    if g_neg and shot_neg and shot_neg.rstrip("；;,，").endswith(g_neg.rstrip("；;,，")):
        allneg = shot_neg
    elif g_neg and shot_neg and g_neg.rstrip("；;,，").endswith(shot_neg.rstrip("；;,，")):
        allneg = g_neg
    elif g_neg and shot_neg:
        allneg = shot_neg + "；" + g_neg
    else:
        allneg = shot_neg or g_neg
    negsec = "【负面】" + allneg if allneg else ""

    parts = [p for p in [legend, gsec, scene, negsec] if p]
    return "\n\n".join(parts)


def get_project_globals(project_id):
    """从 project_configs 读取 __globals__（含 character_voices 扩展字段）。

    这是全局设定的【唯一】访问器：pipeline_service._get_global_settings 与
    routes/project_globals.py 现均委托此处，避免三处重复解析 system_prompts。
    """
    if not project_id:
        return {}
    try:
        import json
        from web.models.database import ProjectConfig
        cfg = ProjectConfig.query.filter_by(project_id=project_id).first()
        if not cfg or not cfg.system_prompts:
            return {}
        return json.loads(cfg.system_prompts).get("__globals__", {})
    except Exception:
        return {}


# 兼容旧名（仅 gen_s02_package.py 历史引用）
get_project_globals_dict = get_project_globals


def inject_globals(shot, g):
    """幂等、去重地把项目全局设定注入分镜 shot 的【存储字段】。

    与 build_full_prompt（交付包装）不同，本函数只服务于「生成/落盘」步骤：
    把 positive_prompts 并入 video_prompt、negative_prompts 并入 negative_prompt，
    二者作为独立字段保留（下游 draw_images 单读 negative_prompt 出图，不能并进 video_prompt）。

    - 幂等：shot 已含该段则不重复追加（重跑 gen_prompts 不会累积）。
    - 调用前请先完成【素材参考】图例、角色一致性锁、场景锚的注入（gen_prompts 中顺序如此）。
    返回原地修改后的 shot。
    """
    g = g or {}
    pos = (g.get("positive_prompts") or "").strip().strip("，,；; ")
    neg = (g.get("negative_prompts") or "").strip().strip("，,；; ")
    if pos:
        vp = (shot.get("video_prompt") or "").strip()
        if pos not in vp:
            shot["video_prompt"] = (vp + "，" + pos) if vp else pos
    if neg:
        np_ = (shot.get("negative_prompt") or "").strip()
        if neg not in np_:
            shot["negative_prompt"] = (np_ + "；" + neg) if np_ else neg
    return shot
