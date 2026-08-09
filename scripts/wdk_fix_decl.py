# -*- coding: utf-8 -*-
"""修正《末日快递王》已落盘提示词的【素材参考】编号（不重跑 LLM）：
   之前 gen_prompts 用「本章局部图例」编号，与打包「全局图例」错位。
   修复后口径：全局图例 = 读盘前序章节 + 本章 拼接统一编号。
   本脚本用同样的全局图例重算每个 shot 的声明 + asset_refs（重写 video_prompt 首段），
   然后重新打包，并断言「声明图号 ↔ 图例 name ↔ 0N.jpg 文件名」三者一致。
"""
import os
import sys
import re
import json

os.environ["AI_DIRECTOR_OFFLINE"] = "0"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from web import create_app
from web.services.storyboard_assets import (
    build_legend_from_shots, read_prompt_shots, refs_for_shot, declaration_for_shot,
)

app = create_app()
client = app.test_client()
ROOT_PATH = app.config["ROOT_PATH"]
PROJECT = "末日快递王"
REPORT = {"errors": []}


def log(*a):
    print("[FIX]", *a, flush=True)


def check(cond, msg):
    if not cond:
        REPORT["errors"].append(msg)
        print(f"[FAIL] {msg}", flush=True)
    return cond


def get_pid(name):
    r = client.get("/api/projects")
    for p in r.get_json():
        if p["name"] == name:
            return p["id"]
    return None


def fix_declarations():
    prompt_dir = os.path.join(ROOT_PATH, "02_Projects", PROJECT, "07_Prompt")
    shots_all = read_prompt_shots(ROOT_PATH, PROJECT)
    legend, legend_idx = build_legend_from_shots(shots_all)
    log(f"全局图例 {len(legend)} 项；前6：", [(e["index"], e["name"]) for e in legend[:6]])

    n_fixed = 0
    for fn in sorted(os.listdir(prompt_dir)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(prompt_dir, fn)
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        chars = d.get("characters") or []
        loc = d.get("location") or ""
        decl_shot = {"characters": chars, "location": loc}
        decl = declaration_for_shot(decl_shot, legend_idx)
        refs = refs_for_shot(decl_shot, legend_idx)

        vp = d.get("video_prompt") or ""
        # 去掉旧【素材参考】首段（首段到首个空行）
        vp_clean = re.sub(r"^【素材参考】.*?(\n\n|$)", "", vp, flags=re.S).strip()
        if vp_clean.startswith("【素材参考】"):  # 无空行分隔的兜底
            vp_clean = vp_clean.split("\n", 1)[-1].strip()
        if decl:
            d["video_prompt"] = (decl + "\n\n" + vp_clean) if vp_clean else decl
        else:
            d["video_prompt"] = vp_clean
        d["asset_refs"] = [{"fig": f"图{idx}", "kind": kind, "name": name}
                           for idx, kind, name in refs]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        n_fixed += 1
    log(f"已重写 {n_fixed} 个分镜提示词声明")
    return legend


_DECL_RE = re.compile(r"图(\d+)=([^()\s]+?)\((角色|场景)图\)")


def assert_consistency(export_dir, legend):
    # 读 package 的 index.json
    with open(os.path.join(export_dir, "index.json"), encoding="utf-8") as f:
        idx = json.load(f)
    legend_by_idx = {e["index"]: e["name"] for e in idx.get("legend", [])}
    asset_map = idx.get("asset_map", {})  # fig文件名 -> {fig, name}

    # 1) index.json 内 legend 与 asset_map 的 fig->name 应一致
    for fname, info in asset_map.items():
        fig_num = int(info["fig"].replace("图", ""))
        check(legend_by_idx.get(fig_num) == info["name"],
              f"asset_map {fname} 图号{fig_num} 与 legend 不一致")

    # 2) 每个 shot 的声明图号 -> name，应与 legend 对应
    mism = 0
    for sh in idx.get("shots", []):
        vp = sh.get("video_prompt", "")
        if "【素材参考】" not in vp:
            continue
        head = vp.split("\n")[0]
        for m in _DECL_RE.finditer(head):
            num = int(m.group(1))
            name = m.group(2)
            expect = legend_by_idx.get(num)
            if expect != name:
                mism += 1
                if mism <= 5:
                    print(f"  [MISMATCH] {sh['file']}: 图{num} 声明={name} 但图例={expect}", flush=True)
    check(mism == 0, f"声明图号与图例 name 错位共 {mism} 处")
    log(f"一致性断言：legend {len(legend_by_idx)} 项，错位 {mism} 处")


def main():
    pid = get_pid(PROJECT)
    assert pid, f"项目 {PROJECT} 不存在"

    legend = fix_declarations()

    # 重新打包（08_Image 已有占位图，无需重导）
    a = client.post(f"/api/asset-packages/{pid}/analyze", json={}).get_json()
    c = client.post(f"/api/asset-packages/{pid}/create",
                    json={"name": "末日快递王_前3章打包_v2"}).get_json()
    e = client.post(f"/api/asset-packages/packages/{c['id']}/export", json={}).get_json()
    log(f"export ok={e.get('ok')} dir={e.get('export_dir')} "
        f"count={e.get('exported_count')} error={e.get('error')}")
    check(e.get("ok") is True, f"打包失败：{e.get('error')}")

    if e.get("ok"):
        assert_consistency(e["export_dir"], legend)

    print("\n========== 汇总 ==========", flush=True)
    print(f"[RESULT] errors={len(REPORT['errors'])}", flush=True)
    if REPORT["errors"]:
        print("ERRORS:", json.dumps(REPORT["errors"], ensure_ascii=False), flush=True)
        sys.exit(1)
    print("[DONE] 编号一致性修复并验证通过", flush=True)


if __name__ == "__main__":
    main()
