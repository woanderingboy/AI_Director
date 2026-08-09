# -*- coding: utf-8 -*-
"""末日快递王 补跑：07_Prompt 已生成（含【素材参考】声明 + asset_refs），
   本脚本只做：收集图例名字 -> 为每个名字导入占位图(08_Image) -> 打包导出 -> 声明检查。
   不重跑 LLM（省额度）。换机/替换章节后想重新打包，跑 run_wdk.py 整条即可。
"""
import os
import sys
import io
import json

os.environ["AI_DIRECTOR_OFFLINE"] = "0"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from web import create_app
from PIL import Image

app = create_app()
client = app.test_client()
ROOT_PATH = app.config["ROOT_PATH"]

PROJECT_NAME = "末日快递王"
PKG_NAME = "末日快递王_前3章打包"
REPORT = {"steps": [], "errors": []}


def log(step, **kw):
    REPORT["steps"].append({"step": step, **kw})
    print(f"[STEP] {step} -> {json.dumps(kw, ensure_ascii=False)}", flush=True)


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


def collect_legend_names(name):
    d = os.path.join(ROOT_PATH, "02_Projects", name, "07_Prompt")
    names, seen = [], set()
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(d, fn), encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            for r in data.get("asset_refs") or []:
                nm = r.get("name")
                if nm and nm not in seen:
                    seen.add(nm)
                    names.append(nm)
            for c in data.get("characters") or []:
                if c not in seen:
                    seen.add(c)
                    names.append(c)
            loc = data.get("location")
            if loc and loc not in seen:
                seen.add(loc)
                names.append(loc)
    log("collect_legend", count=len(names), names=names)
    return names


def import_placeholder(pid, asset_name, color=(120, 80, 200)):
    img = Image.new("RGB", (96, 96), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    r = client.post(
        f"/api/import/{pid}/import-image",
        data={"file": (buf, "sample.png"), "asset_name": asset_name},
        content_type="multipart/form-data",
    )
    j = r.get_json()
    ok = r.status_code == 200 and j.get("ok")
    log("import_placeholder", name=asset_name, ok=ok)
    return ok


def export_package(pid, name, pkg_name):
    a = client.post(f"/api/asset-packages/{pid}/analyze", json={}).get_json()
    c = client.post(f"/api/asset-packages/{pid}/create", json={"name": pkg_name}).get_json()
    e = client.post(f"/api/asset-packages/packages/{c['id']}/export", json={}).get_json()
    log("export_package", ok=e.get("ok"), export_dir=e.get("export_dir"),
        exported_count=e.get("exported_count"), error=e.get("error"))
    return a, c, e


def first_decl_sample(name):
    d = os.path.join(ROOT_PATH, "02_Projects", name, "07_Prompt")
    out = []
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".json"):
                continue
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                data = json.load(f)
            vp = data.get("video_prompt") or data.get("prompt") or ""
            if "【素材参考】" in vp:
                out.append({"file": fn, "head": vp.split("\n")[0]})
                if len(out) >= 3:
                    return out
    return out


def main():
    pid = get_pid(PROJECT_NAME)
    assert pid, f"项目 {PROJECT_NAME} 不存在，请先跑 run_wdk.py"
    log("project", id=pid)

    names = collect_legend_names(PROJECT_NAME)
    n_ok = 0
    for nm in names:
        if import_placeholder(pid, nm):
            n_ok += 1
    log("imported_placeholders", total=len(names), ok=n_ok)

    a, c, e = export_package(pid, PROJECT_NAME, PKG_NAME)

    check(e.get("ok") is True, f"打包应成功：{e.get('error') or e.get('message')}")
    if e.get("ok"):
        idx = e.get("index_json", {})
        legend = idx.get("legend", [])
        check(len(legend) > 0, "index.json 应含 legend 图例")
        exported_files = sorted(os.listdir(e.get("export_dir", ""))) if e.get("export_dir") else []
        log("exported_files", files=exported_files)
        numbered = [f for f in exported_files if f[:2].isdigit()]
        check(len(numbered) > 0, "导出应含 01/02… 命名文件")
        # 读出 index.json 图例前 8 项展示
        log("index_legend_head", legend=legend[:8])

    decls = first_decl_sample(PROJECT_NAME)
    log("decl_sample", samples=decls)
    check(len(decls) > 0, "至少一条分镜提示词应含【素材参考】声明")

    print("\n========== 汇总 ==========", flush=True)
    print(json.dumps(REPORT, ensure_ascii=False, indent=2), flush=True)
    print(f"\n[RESULT] errors={len(REPORT['errors'])}", flush=True)
    if REPORT["errors"]:
        print("ERRORS:", json.dumps(REPORT["errors"], ensure_ascii=False), flush=True)
        sys.exit(1)
    print("[DONE] 打包完成", flush=True)


if __name__ == "__main__":
    main()
