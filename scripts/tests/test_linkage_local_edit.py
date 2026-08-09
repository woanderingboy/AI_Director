# -*- coding: utf-8 -*-
"""用户多操作联动测试矩阵（离线模式，零额度）。

覆盖用户可能进行的多种操作，重点验证：
  1) 局部修改上游（小说/场景/删除）→ 下游产物是否被标 stale（联动诊断）
  2) 重跑下游 → stale 是否被清除（联动修复）
  3) 用户在分镜画布手改提示词 / 标记最终版 → 重跑是否被覆盖（联动保护缺陷检测）
  4) 角色一致性锁注入（联动回归）
  5) 越界/缺失/重复导入等边界是否优雅报错（不 500）
  6) scan-novels 重复扫描幂等

关键实现注意：
  - novel_chapters 蓝图前缀是 /api/novel；characters 的 lock 路由还需 project_id 段。
  - PipelineService.run_all 内部用 `if progress and ...` 守卫后续阶段，
    故必须传入一个非 None 的 DummyProgress，否则 gen_prompts/draw_images/render_videos 不会执行。

结论写 UTF-8 JSON（C:/Users/Administrator/AppData/Local/Temp/linkage_result.json）。
"""
import os
import sys
import io
import json
import glob
import time
import shutil

# Windows 控制台默认 GBK，含中文的 print 会抛 UnicodeEncodeError；强制 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

os.environ["AI_DIRECTOR_OFFLINE"] = "1"  # 必须在 import web 之前

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

RESULT = "C:/Users/Administrator/AppData/Local/Temp/linkage_result.json"
OUT = []
PASS = []
FAIL = []
WARN = []


def emit(msg):
    OUT.append(msg)
    print(msg, flush=True)


def check(name, cond, detail="", severity="FAIL"):
    bucket = PASS if cond else (WARN if severity == "WARN" else FAIL)
    bucket.append(name)
    tag = "PASS" if cond else ("WARN" if severity == "WARN" else "FAIL")
    emit(f"[{tag}] {name}" + (f" — {detail}" if detail else ""))


class DummyProgress:
    """让 run_all 真正执行全部阶段（其内置 `if progress and ...` 守卫）。"""
    def update(self, **kw):
        pass
    def is_cancelled(self):
        return False
    def check_interrupt(self):
        return None


from web import create_app
from web.models.database import db, ScriptModel, ProjectModel
from web.models.novel_models import NovelChapter
from web.models.asset_models import AssetVersion
from web.services.pipeline_service import PipelineService
from PIL import Image

app = create_app()
client = app.test_client()
ROOT_PATH = app.config["ROOT_PATH"]
TS = time.strftime("%m%d_%H%M%S")


# ───────── helpers ─────────
def unique_name(p):
    return f"{p}_{TS}"


def orphan_av_cleanup():
    """清理上一轮测试遗留的 AssetVersion：项目已被删除（孤儿）的版本。
    只删孤儿，不动真实项目（末日快递王等）的版本，避免污染真实数据。"""
    try:
        with app.app_context():
            alive = {p.id for p in ProjectModel.query.all()}
            if not alive:
                return
            n = AssetVersion.query.filter(AssetVersion.project_id.notin_(alive)).delete()
            db.session.commit()
            emit(f"  清理孤儿 AssetVersion: {n}")
    except Exception as e:
        emit(f"  orphan_av_cleanup 跳过: {e}")


def cleanup(pid, name):
    try:
        client.delete(f"/api/projects/{pid}")
    except Exception:
        pass
    # 项目删除不级联 AssetVersion；显式清理本项目的最终版标记，避免泄漏到下一轮
    try:
        with app.app_context():
            AssetVersion.query.filter_by(project_id=pid).delete()
            db.session.commit()
    except Exception:
        pass
    d = os.path.join(ROOT_PATH, "02_Projects", name)
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)


def get_project(pid):
    return client.get(f"/api/projects/{pid}").get_json()


def freshness(pid):
    return client.get(f"/api/projects/{pid}/freshness").get_json()


def prompt_files(name):
    d = os.path.join(ROOT_PATH, "02_Projects", name, "07_Prompt")
    return sorted(glob.glob(os.path.join(d, "*_prompt_*.json")))


def read_prompt(fp):
    return json.load(open(fp, encoding="utf-8"))


def write_prompt(fp, data):
    json.dump(data, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def stages_stale(fr, keys):
    st = fr.get("stages", {})
    return {k: st.get(k, {}).get("stale") for k in keys}


# ───────── 阶段 ─────────
def phase1_baseline(pid, name):
    emit("── P1 基线：离线四阶段 + 初始 freshness ──")
    sd = os.path.join(ROOT_PATH, "02_Projects", name, "04_Story")
    os.makedirs(sd, exist_ok=True)
    with open(os.path.join(sd, "source.txt"), "w", encoding="utf-8") as f:
        f.write(
            "第一章 离站\n林深在站台回望城市，背着背包。\n"
            "第二章 初遇\n林深在咖啡馆遇见撑黑伞的苏晚。\n"
        )
    scan = client.post(f"/api/import/{pid}/scan-novels", json={}).get_json()
    emit(f"  scan: {scan}")
    with app.app_context():
        chs = NovelChapter.query.filter_by(project_id=pid).order_by(NovelChapter.chapter_number).all()
    check("P1 章节入库(scan)", len(chs) >= 1, f"chapters={len(chs)}")
    if not chs:
        return []
    svc = PipelineService(ROOT_PATH)
    with app.app_context():
        s1 = svc.novel_to_script(project_name=name, chapter_id=chs[0].id, project_id=pid)
        check("P1 小说→剧本产出镜头", s1.get("shot_count", 0) > 0, f"shots={s1.get('shot_count')}")
        sc = ScriptModel.query.filter_by(novel_chapter_id=chs[0].id).order_by(ScriptModel.id.desc()).first()
        s2 = svc.gen_prompts(project_name=name, chapter_id=chs[0].id, script_id=sc.id, project_id=pid)
        check("P1 剧本→提示词产出", s2.get("shots", 0) > 0, f"files={len(s2.get('files', []))}")
        s3 = svc.draw_images(project_id=pid, project_name=name)
        check("P1 提示词→图片(离线占位)", s3.get("status") == "ok", f"count={s3.get('count')}")
        s4 = svc.render_videos(project_id=pid, project_name=name)
        check("P1 图片→视频(离线)", s4.get("status") == "ok", f"count={s4.get('count')}")
    for sub in ["05_Script", "07_Prompt", "08_Image", "09_Video"]:
        dd = os.path.join(ROOT_PATH, "02_Projects", name, sub)
        mk = os.path.exists(os.path.join(dd, ".novel_version"))
        check(f"P1 {sub} 版本标记存在", mk)
    fr = freshness(pid)
    check("P1 初始无 stale", fr.get("any_stale") is False, json.dumps(stages_stale(fr, ["script", "prompt", "image", "video"]), ensure_ascii=False))
    return chs


def phase2_edit_chapter_stale(pid, name, chs):
    emit("── P2 局部修改小说章节 → 下游 stale 联动（核心）──")
    if not chs:
        check("P2 前置章节缺失", False)
        return
    ch0 = chs[0]
    pfs = prompt_files(name)
    fp0 = pfs[0] if pfs else None
    before = read_prompt(fp0)["video_prompt"] if fp0 else ""
    r = client.put(f"/api/novel/novel-chapters/{ch0.id}", json={"content": "【修改后】林深在站台回望，决心离开这座城市。"})
    check("P2 改章节内容200", r.status_code == 200, str(r.status_code))
    v = get_project(pid).get("novel_version")
    check("P2 novel_version 递增到1", v == 1, f"v={v}")
    fr = freshness(pid)
    st = stages_stale(fr, ["script", "prompt", "image", "video"])
    check("P2 四类产物全 stale(联动标记)", all(st.values()), json.dumps(st, ensure_ascii=False))
    if fp0:
        after = read_prompt(fp0)["video_prompt"]
        check("P2 改上游仅标 stale、未自动改写下游文件", after == before, "下游保留旧产物，仅标记过期")


def phase3_scene_and_delete(pid, name, chs):
    emit("── P3 场景改动/删除/新建 → bump 联动 ──")
    if not chs:
        check("P3 前置章节缺失", False)
        return
    ch0 = chs[0]
    r = client.post(f"/api/novel/novel-chapters/{ch0.id}/scenes", json={"title": "测试场景", "content": "原内容"})
    emit(f"  create scene: status={r.status_code} body={r.get_data(as_text=True)[:160]}")
    check("P3 建场景201", r.status_code == 201, str(r.status_code))
    j = r.get_json() or {}
    sid = j.get("id")
    r = client.put(f"/api/novel/scenes/{sid}", json={"content": "【改后】场景内容更新"})
    check("P3 改场景200", r.status_code == 200)
    check("P3 改场景 bump 到2", get_project(pid).get("novel_version") == 2, f"v={get_project(pid).get('novel_version')}")
    r = client.delete(f"/api/novel/scenes/{sid}")
    check("P3 删场景200", r.status_code == 200)
    check("P3 删场景 bump 到3", get_project(pid).get("novel_version") == 3, f"v={get_project(pid).get('novel_version')}")
    ch1 = chs[1] if len(chs) > 1 else None
    if ch1:
        r = client.delete(f"/api/novel/novel-chapters/{ch1.id}")
        check("P3 删章节200(级联无异常)", r.status_code == 200)
        check("P3 删章节 bump 到4", get_project(pid).get("novel_version") == 4, f"v={get_project(pid).get('novel_version')}")
    v_before = get_project(pid).get("novel_version")
    r = client.post(f"/api/novel/{pid}/novel-chapters", json={"title": "新建章", "content": "x"})
    check("P3 新建章节201", r.status_code == 201, str(r.status_code))
    v_after = get_project(pid).get("novel_version")
    check("P3 新建章节不 bump(已知特性/潜在漏标)", v_after == v_before,
          f"before={v_before} after={v_after}", severity="WARN")


def phase4_rerun(pid, name, chs0_id):
    emit("── P4 重跑下游 → stale 清除（核心联动）──")
    svc = PipelineService(ROOT_PATH)
    with app.app_context():
        svc.run_all(project_name=name, chapter_id=chs0_id, project_id=pid, progress=DummyProgress())
    fr = freshness(pid)
    st = stages_stale(fr, ["script", "prompt", "image", "video"])
    check("P4 重跑后全无 stale(联动清除)", not any(st.values()), json.dumps(st, ensure_ascii=False))
    check("P4 产物版本标记对齐 novel_version", fr.get("novel_version") == get_project(pid).get("novel_version"),
          f"fr={fr.get('novel_version')} proj={get_project(pid).get('novel_version')}")


def phase5_final_protection(pid, name, chs0_id):
    emit("── P5 用户在分镜画布手改 + 标记最终版 → 重跑是否被覆盖（联动保护缺陷检测）──")
    pfs = prompt_files(name)
    if not pfs:
        check("P5 有提示词文件可测", False)
        return
    fp = pfs[0]
    data = read_prompt(fp)
    tag = "【用户精修标记XYZ】"
    data["video_prompt"] = (data.get("video_prompt", "") or "") + tag
    write_prompt(fp, data)
    with open(fp, "rb") as f:
        r = client.post(
            f"/api/import/{pid}/import-external",
            data={"file": (f, os.path.basename(fp), "application/json"), "kind": "prompt",
                  "asset_key": os.path.splitext(os.path.basename(fp))[0], "as_final": "true"},
            content_type="multipart/form-data",
        )
    j = r.get_json()
    check("P5 标记最终版操作返回 ok", j.get("ok") is True, str(r.status_code))
    with app.app_context():
        row = AssetVersion.query.filter_by(project_id=pid, asset_type="storyboard_prompt", is_final=True).first()
    check("P5 最终版已登记(is_final=1)", row is not None)
    # 用户点「重跑下游」（带 progress，确保真正重跑 gen_prompts）
    svc = PipelineService(ROOT_PATH)
    with app.app_context():
        svc.run_all(project_name=name, chapter_id=chs0_id, project_id=pid, progress=DummyProgress())
    new_data = read_prompt(fp)
    preserved = tag in (new_data.get("video_prompt") or "")
    check("P5 重跑保留手改分镜(final 保护)", preserved,
          "重跑后用户精修(【用户精修标记XYZ】)已保留，gen_prompts 未覆盖已定版分镜" if preserved
          else "缺陷：重跑覆盖了用户已定版分镜", severity="FAIL")


def phase6_consistency_lock(pid, name):
    emit("── P6 角色一致性锁注入（联动回归）──")
    r = client.post(f"/api/novel/{pid}/characters", json={"name": "林深", "role": "主角", "appearance": "黑衣", "personality": "沉默"})
    check("P6 创建角色200/201", r.status_code in (200, 201), str(r.status_code))
    j = r.get_json() or {}
    cid = j.get("id")
    emit(f"  created character id={cid}")
    r = client.post(f"/api/novel/{pid}/characters/{cid}/lock", json={"consistency_lock": True})
    check("P6 开启一致性锁200", r.status_code == 200, str(r.status_code))
    hit = any("【角色一致性锁定" in (read_prompt(fp).get("video_prompt") or "") for fp in prompt_files(name))
    check("P6 一致性锁注入(若剧本引用该角色)", hit,
          "离线剧本未引用该角色名则未触发(环境限制，非缺陷)", severity="WARN")


def phase7_boundaries(pid, name):
    emit("── P7 边界/异常（是否报错、是否优雅）──")
    img = Image.new("RGB", (32, 32), (100, 120, 200))
    KEY = f"边界素材_{TS}"

    def _png():
        b = io.BytesIO()
        img.save(b, format="PNG")
        b.seek(0)
        return b

    # 7.5 重复导入同一素材 → 幂等
    client.post(f"/api/import/{pid}/import-external",
                data={"file": (_png(), "b.png", "image/png"), "kind": "asset", "asset_key": KEY},
                content_type="multipart/form-data")
    with app.app_context():
        cnt_before = AssetVersion.query.filter_by(project_id=pid, asset_type="reference", asset_key=KEY).count()
    r2 = client.post(f"/api/import/{pid}/import-external",
                     data={"file": (_png(), "b.png", "image/png"), "kind": "asset", "asset_key": KEY},
                     content_type="multipart/form-data")
    with app.app_context():
        cnt_after = AssetVersion.query.filter_by(project_id=pid, asset_type="reference", asset_key=KEY).count()
    check("P7 重复导入同素材幂等(不新建版本)", cnt_after == cnt_before and r2.get_json().get("reused") is True,
          f"before={cnt_before} after={cnt_after} reused={r2.get_json().get('reused')}")
    # 7.6 缺文件
    r = client.post(f"/api/import/{pid}/import-external", data={"kind": "asset"})
    check("P7 缺文件导入返回400(非500)", r.status_code == 400, str(r.status_code))
    # 7.7 非法 kind
    r = client.post(f"/api/import/{pid}/import-external",
                    data={"file": (io.BytesIO(b"x"), "a.png"), "kind": "xxx"},
                    content_type="multipart/form-data")
    check("P7 非法 kind 返回400", r.status_code == 400, str(r.status_code))
    # 7.8 非法 prompt JSON
    r = client.post(f"/api/import/{pid}/import-external",
                    data={"file": (io.BytesIO(b"this is not json"), "x.json"), "kind": "prompt"},
                    content_type="multipart/form-data")
    check("P7 非法 prompt JSON 返回400", r.status_code == 400, str(r.status_code))

    # 7.4 删除项目后再访问 freshness → 404
    r = client.delete(f"/api/projects/{pid}")
    check("P7 删除项目200", r.status_code == 200, str(r.status_code))
    r = client.get(f"/api/projects/{pid}/freshness")
    check("P7 删后访问 freshness 返回404", r.status_code == 404, str(r.status_code))

    # 7.1 / 7.2 / 7.3 越界 id → 404
    r = client.get(f"/api/novel/novel-chapters/9999999")
    check("P7 越界 GET 章节返回404", r.status_code == 404, str(r.status_code))
    r = client.put(f"/api/novel/novel-chapters/9999999", json={"content": "x"})
    check("P7 越界 PUT 章节返回404", r.status_code == 404, str(r.status_code))
    r = client.get(f"/api/projects/9999999/freshness")
    check("P7 越界 GET 项目 freshness 返回404", r.status_code == 404, str(r.status_code))


def phase8_scan_idempotent(pid, name):
    emit("── P8 scan-novels 重复扫描幂等 ──")
    with app.app_context():
        before = NovelChapter.query.filter_by(project_id=pid).count()
    client.post(f"/api/import/{pid}/scan-novels", json={})
    with app.app_context():
        after = NovelChapter.query.filter_by(project_id=pid).count()
    check("P8 重复 scan 不重复建章节", after == before, f"before={before} after={after}")


def main():
    orphan_av_cleanup()  # 先清掉上一轮遗留的孤儿 AssetVersion（最终版标记泄漏）
    name = unique_name("联动_本地修改")
    r = client.post("/api/projects", json={"name": name, "description": "linkage test", "genre": "测试"})
    check("建项目201", r.status_code == 201, str(r.status_code))
    pid = r.get_json()["id"] if r.status_code == 201 else None
    try:
        if pid is None:
            return
        chs = phase1_baseline(pid, name)
        chs0_id = chs[0].id if chs else None
        if chs0_id is not None:
            phase2_edit_chapter_stale(pid, name, chs)
            phase3_scene_and_delete(pid, name, chs)
            phase4_rerun(pid, name, chs0_id)
            phase5_final_protection(pid, name, chs0_id)
        phase6_consistency_lock(pid, name)
        phase8_scan_idempotent(pid, name)  # 删项目前做
        phase7_boundaries(pid, name)        # 内部包含删除项目 + 越界
    except Exception as e:
        import traceback
        emit(f"EXCEPTION: {repr(e)}")
        emit(traceback.format_exc())
    finally:
        if pid:
            cleanup(pid, name)
        dump()
        print(f"\n===== 联动测试汇总 =====\nPASS={len(PASS)} FAIL={len(FAIL)} WARN={len(WARN)}")
        if FAIL:
            print("FAIL:", FAIL)
        if WARN:
            print("WARN:", WARN)


def dump():
    with open(RESULT, "w", encoding="utf-8") as f:
        json.dump({"PASS": PASS, "FAIL": FAIL, "WARN": WARN, "LOG": OUT}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
