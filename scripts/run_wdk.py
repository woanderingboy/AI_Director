# -*- coding: utf-8 -*-
"""跑《末日快递王》前 3 章（用户给的 inkos chapters）：
   源文本导入(scan-novels) -> novel2script -> gen_prompts -> 占位角色/场景参考图 -> 打包导出
   验证：① 真实 LLM 把小说转分镜提示词；② 每条提示词首段【素材参考】声明；
        ③ 打包按图例顺序重命名 01.jpg/02.jpg… + index.json 图例映射。
   真实 LLM（AI_DIRECTOR_OFFLINE=0），不跑 draw_images（省出图额度），资产图用 PIL 占位。
   后续替换章节：直接重新运行本脚本即可（自动清空旧源+旧章节，幂等）。
"""
import os
import sys
import io
import json
import time
import glob
import shutil

# 强制在线（必须在 import web 之前设置，dotenv 不会覆盖已存在的环境变量）
os.environ["AI_DIRECTOR_OFFLINE"] = "0"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from web.services.storyboard_assets import build_legend_from_shots
from web import create_app
from web.models.database import db, ProjectModel, ScriptModel
from web.models.novel_models import NovelChapter
from web.services.pipeline_service import PipelineService
from PIL import Image, ImageDraw

app = create_app()
client = app.test_client()
ROOT_PATH = app.config["ROOT_PATH"]

# 用户给的 3 章（inkos chapters），只跑这 3 章，不擅自动其余 18 章
SRC_CHAPTERS = [
    r"D:\AI_Inkos\my-novel\books\末日快递王\chapters\0001_最后一单.md",
    r"D:\AI_Inkos\my-novel\books\末日快递王\chapters\0002_便利店截流.md",
    r"D:\AI_Inkos\my-novel\books\末日快递王\chapters\0003_站点.md",
]
PROJECT_NAME = "末日快递王"
PROJECT_DESC = "inkos 小说《末日快递王》前3章（源文本导入，待定稿）"

REPORT = {"steps": [], "errors": []}


def log(step, **kw):
    REPORT["steps"].append({"step": step, **kw})
    print(f"[STEP] {step} -> {json.dumps(kw, ensure_ascii=False)}", flush=True)


def check(cond, msg):
    if not cond:
        REPORT["errors"].append(msg)
        print(f"[FAIL] {msg}", flush=True)
    return cond


def llm_call(fn, *a, retries=4, **kw):
    """带重试的 LLM 调用（火山端点偶发抖动）。"""
    last = None
    for i in range(retries):
        try:
            return fn(*a, **kw)
        except Exception as e:
            last = e
            wait = 3 * (i + 1)
            print(f"  [retry {i+1}/{retries}] {e} -> sleep {wait}s", flush=True)
            time.sleep(wait)
    raise last


def ensure_project(name, desc):
    """存在则复用（并清空旧源+旧章节，保证替换幂等）；不存在则创建。"""
    r = client.get("/api/projects")
    for p in r.get_json():
        if p["name"] == name:
            pid = p["id"]
            log("reuse_project", name=name, id=pid)
            # 清空旧源文件
            story_dir = os.path.join(ROOT_PATH, "02_Projects", name, "04_Story")
            if os.path.isdir(story_dir):
                for fn in os.listdir(story_dir):
                    if fn.lower().endswith((".md", ".txt")):
                        os.remove(os.path.join(story_dir, fn))
            # 清空旧章节（DB）
            with app.app_context():
                NovelChapter.query.filter_by(project_id=pid).delete()
                db.session.commit()
            return pid
    r = client.post("/api/projects", json={"name": name, "description": desc, "genre": "废土"})
    assert r.status_code == 201, f"建项目失败 {r.status_code} {r.get_data(as_text=True)[:200]}"
    pid = r.get_json()["id"]
    log("create_project", name=name, id=pid)
    return pid


def copy_chapters(name, src_list):
    d = os.path.join(ROOT_PATH, "02_Projects", name, "04_Story")
    os.makedirs(d, exist_ok=True)
    imported = []
    for src in src_list:
        if not os.path.exists(src):
            check(False, f"源章节不存在: {src}")
            continue
        dst = os.path.join(d, os.path.basename(src))
        shutil.copy2(src, dst)
        imported.append(os.path.basename(src))
    log("copy_chapters", count=len(imported), files=imported)
    return imported


def scan_novels(pid):
    r = client.post(f"/api/import/{pid}/scan-novels", json={})
    j = r.get_json()
    log("scan_novels", **j)
    return j


def run_pipeline_direct(pid, name, ch_id):
    with app.app_context():
        svc = PipelineService(ROOT_PATH)
        s1 = llm_call(svc.novel_to_script, project_name=name, chapter_id=ch_id, project_id=pid)
        sc = (
            ScriptModel.query.filter_by(novel_chapter_id=ch_id)
            .order_by(ScriptModel.id.desc())
            .first()
        )
        assert sc, "novel_to_script 未生成 ScriptModel"
        s2 = llm_call(svc.gen_prompts, project_name=name, chapter_id=ch_id, script_id=sc.id, project_id=pid)
    log("novel_to_script", filename=s1.get("filename"), shot_count=s1.get("shot_count"))
    log("gen_prompts", shots=s2.get("shots"), files=len(s2.get("files", [])))
    return s1, s2


def collect_legend_names(name):
    # 07_Prompt 下每个分镜是单独 json（含 asset_refs / characters / location）
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
            # 优先用 asset_refs（已含 fig/name/kind，顺序即图例顺序）
            for r in data.get("asset_refs") or []:
                nm = r.get("name")
                if nm and nm not in seen:
                    seen.add(nm)
                    names.append(nm)
            # 兜底：从 characters/location 收集
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


def import_placeholder_image(pid, asset_name, color=(120, 80, 200)):
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
    log("export_package", analyze=a, create=c, export=e)
    return a, c, e


def first_decl_sample(name):
    """返回前几条含【素材参考】的 video_prompt 首段，用于报告展示。"""
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
                out.append((fn, vp.split("\n")[0]))
                if len(out) >= 3:
                    return out
    return out


def main():
    pid = ensure_project(PROJECT_NAME, PROJECT_DESC)
    copy_chapters(PROJECT_NAME, SRC_CHAPTERS)
    scan = scan_novels(pid)
    with app.app_context():
        chs = NovelChapter.query.filter_by(project_id=pid).order_by(NovelChapter.chapter_number).all()
    check(len(chs) >= 1, f"至少应导入 1 章，实际 {len(chs)}")
    log("chapters_imported", count=len(chs), titles=[c.title for c in chs])

    total_shots = 0
    for ch in chs:
        s1, s2 = run_pipeline_direct(pid, PROJECT_NAME, ch.id)
        total_shots += s2.get("shots", 0) or 0
    log("total_shots", total=total_shots)

    # 收集图例名字 -> 为每个名字生成占位图按名导入（角色+场景都导，演示完整图例映射）
    legend_names = collect_legend_names(PROJECT_NAME)
    for nm in legend_names:
        import_placeholder_image(pid, nm)

    # 打包导出
    a, c, e = export_package(pid, PROJECT_NAME, "末日快递王_前3章打包")

    # 断言
    check(e.get("ok") is True, f"打包应成功：{e.get('error') or e.get('message')}")
    if e.get("ok"):
        idx = e.get("index_json", {})
        legend = idx.get("legend", [])
        check(len(legend) > 0, "index.json 应含 legend 图例")
        exported_files = sorted(os.listdir(e.get("export_dir", ""))) if e.get("export_dir") else []
        log("exported_files", files=exported_files)
        # 验证存在 01/02 命名
        numbered = [f for f in exported_files if f[:2].isdigit()]
        check(len(numbered) > 0, "导出应含 01/02… 命名文件")

    # 提示词首段声明样例
    decls = first_decl_sample(PROJECT_NAME)
    log("decl_sample", samples=[{"file": fn, "head": h} for fn, h in decls])
    check(len(decls) > 0, "至少一条分镜提示词应含【素材参考】声明")

    print("\n========== 汇总 ==========", flush=True)
    print(json.dumps(REPORT, ensure_ascii=False, indent=2), flush=True)
    print(f"\n[RESULT] errors={len(REPORT['errors'])}", flush=True)
    if REPORT["errors"]:
        print("ERRORS:", json.dumps(REPORT["errors"], ensure_ascii=False), flush=True)
        sys.exit(1)
    print("[DONE] 全流程通过", flush=True)


if __name__ == "__main__":
    main()
