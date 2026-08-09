"""分镜素材图例（全局编号）

把分镜里出现的「角色 / 场景」按分镜出现顺序排成全局图例：
    图1 = 苏晚（角色图）
    图2 = 末日废墟（场景图）
    ...

该图例被两处复用，保证「提示词里的图N」与「打包里的 0N.jpg」严格对应：
1. gen_prompts：在每条 video_prompt 开头注入【素材参考】图N=…声明；
2. export_package：按图例顺序将素材文件重命名为 01.jpg / 02.jpg …。
"""
import os
import re
import json


def _norm(s):
    """归一化用于名称匹配：保留中日韩/字母/数字，去掉空白与标点。"""
    if not s:
        return ""
    out = []
    for ch in str(s).lower():
        if ch.isalnum() or "一" <= ch <= "鿿":
            out.append(ch)
    return "".join(out)


_SHOT_RE = re.compile(r"S(\d+)")


def _shot_sort_key(fname):
    m = _SHOT_RE.search(fname)
    return int(m.group(1)) if m else 10 ** 9


def _names_of(shot):
    """从一条分镜抽取 (角色名列表, 场景名)。角色支持 str 或 {name:...}。"""
    chars = []
    for c in (shot.get("characters") or []):
        if isinstance(c, dict):
            c = c.get("name")
        if c and str(c).strip():
            chars.append(str(c).strip())
    loc = (shot.get("location") or "").strip()
    return chars, (loc if loc else None)


def build_legend_from_shots(shots):
    """按分镜出现顺序生成全局素材图例（不依赖磁盘）。

    返回 [{index:int(从1), kind:'角色'|'场景', name:str}, ...]，
    以及 name(归一化)->index 的映射。
    """
    order = []          # (kind, name)
    seen = set()
    legend_idx = {}     # norm(name) -> index

    def add(kind, name):
        n = (name or "").strip()
        if not n:
            return
        key = (kind, _norm(n))
        if key in seen:
            return
        seen.add(key)
        order.append((kind, n))

    for sh in shots or []:
        chars, loc = _names_of(sh)
        for c in chars:
            add("角色", c)
        if loc:
            add("场景", loc)

    legend = [{"index": i + 1, "kind": k, "name": n} for i, (k, n) in enumerate(order)]
    for e in legend:
        legend_idx[_norm(e["name"])] = e["index"]
    return legend, legend_idx


def refs_for_shot(shot, legend_idx):
    """为单条分镜返回其用到的素材图号列表 [(index, kind, name)]（按图号升序）。

    仅含该镜确实引用、且已纳入全局图例的资产。
    """
    refs = []  # (index, kind, name)
    chars, loc = _names_of(shot)
    for c in chars:
        idx = legend_idx.get(_norm(c))
        if idx:
            refs.append((idx, "角色", c))
    if loc:
        idx = legend_idx.get(_norm(loc))
        if idx:
            refs.append((idx, "场景", loc))
    refs.sort(key=lambda x: x[0])
    return refs


def declaration_for_shot(shot, legend_idx):
    """为单条分镜生成【素材参考】声明字符串（仅含该镜用到的图号）。

    返回 "" 表示该镜没有任何可声明的参考素材。
    """
    refs = refs_for_shot(shot, legend_idx)
    if not refs:
        return ""
    parts = [f"图{idx}={name}({kind}图)" for idx, kind, name in refs]
    return "【素材参考】" + "、".join(parts)


def read_prompt_shots(root_path, project_name):
    """读取 07_Prompt 目录下所有分镜 json（按 S 编号排序），返回 shot dict 列表。

    供 build_asset_legend 与 gen_prompts（构建全局图例）复用。
    """
    prompt_dir = os.path.join(root_path, "02_Projects", project_name, "07_Prompt")
    shots = []
    if os.path.isdir(prompt_dir):
        for f in sorted(os.listdir(prompt_dir), key=_shot_sort_key):
            if not f.endswith(".json"):
                continue
            try:
                with open(os.path.join(prompt_dir, f), "r", encoding="utf-8") as fh:
                    d = json.load(fh)
                shots.append(d)
            except Exception:
                continue
    return shots


def build_asset_legend(root_path, project_name):
    """从 07_Prompt 目录读盘，复用 build_legend_from_shots。

    用于打包时（07_Prompt 已落盘）重建与 gen_prompts 完全相同的图例编号。
    """
    return build_legend_from_shots(read_prompt_shots(root_path, project_name))
