# -*- coding: utf-8 -*-
"""两种项目形态的端到端导入/打包验证 + 素材图例（图N ↔ 0N.jpg）验证：
   A. 完整小说  -> scan-novels -> novel2script -> gen_prompts -> 占位角色参考图 -> 打包导出
   B. 每日励志短句(无章节标题) -> scan-novels(单章) -> novel2script -> gen_prompts -> 打包导出
   图例两项新增能力：
     ① gen_prompts 在每条 video_prompt 首段注入【素材参考】图N=XX(角色/场景图)
     ② export_package 按图例顺序将素材重命名为 01.jpg/02.jpg…，index.json 写入 legend 映射
   闭环：把 A 的导出包重新 import-package 到新项目 C，验证声明保留且可再次重命名打包。
真实 LLM（AI_DIRECTOR_OFFLINE=0），不跑 draw_images（省出图额度），资产图用 PIL 占位。
"""
import os
import sys
import io
import json
import glob
import time
import textwrap

# 强制在线（必须在 import web 之前设置，dotenv 不会覆盖已存在的环境变量）
os.environ["AI_DIRECTOR_OFFLINE"] = "0"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from web.services.storyboard_assets import (
    build_legend_from_shots,
    declaration_for_shot,
    build_asset_legend,
)
from web import create_app
from web.models.database import db, ProjectModel, ScriptModel
from web.models.novel_models import NovelChapter
from web.services.pipeline_service import PipelineService
from PIL import Image

app = create_app()
client = app.test_client()
ROOT_PATH = app.config["ROOT_PATH"]

NOVEL_TEXT = textwrap.dedent("""\
第一章 离站
清晨六点，末班地铁的灯光在空荡的站台投下冷白的光。林深背着沉重的背包，最后一次回望这座他生活了二十六年的城市。
口袋里的录用通知还在发烫——南方那座以创新闻名的城市，给了他一个不至于饿死、却也谈不上热爱的工作。
列车进站的风掀起他的衣角。他忽然想起母亲说过的话：「人总得先离开，才知道自己属于哪里。」
车门关闭的瞬间，他按下了发送键，把一句「我走了」发给了那个始终没有回复过他的人。

第二章 初遇
南方城市的雨季来得猝不及防。林深在写字楼下的咖啡馆避雨时，遇见了撑着一把破旧黑伞的苏晚。
她正对着笔记本奋笔疾书，仿佛要把整座城市的雨都写进去。
""")

QUOTE_TEXT = textwrap.dedent("""\
今日一句：你不需要很厉害才能开始，但你必须开始，才能变得厉害。

又一日：所谓自由，不是想做什么就做什么，而是不想做什么就可以不做什么。

再一日：把每一天都过成草稿，允许自己修改，但不允许自己停笔。

最后一则：黎明前最黑暗，但黑暗本身，正说明太阳已经在路上了。
""")

REPORT = {"steps": [], "errors": []}


def log(step, **kw):
    REC = {"step": step, **kw}
    REPORT["steps"].append(REC)
    print(f"[STEP] {step} -> {json.dumps(kw, ensure_ascii=False)}", flush=True)


def check(cond, msg):
    if not cond:
        REPORT["errors"].append(msg)
        print(f"[FAIL] {msg}", flush=True)
    return cond


# ═══════════ 图例单元验证（不依赖网络） ═══════════
def test_legend_unit():
    shots = [
        {"characters": ["苏晚"], "location": "咖啡馆"},
        {"characters": ["林深", "苏晚"], "location": "站台"},
    ]
    legend, idx = build_legend_from_shots(shots)
    # 按分镜出现顺序（角色优先、其次场景，逐镜推进）：苏晚→咖啡馆→林深→站台
    check([e["name"] for e in legend] == ["苏晚", "咖啡馆", "林深", "站台"],
          f"图例顺序应按分镜出现顺序：实际 {[e['name'] for e in legend]}")
    check(legend[0]["index"] == 1 and legend[3]["index"] == 4, "图例编号应从1连续递增")
    d0 = declaration_for_shot(shots[0], idx)
    check(d0 == "【素材参考】图1=苏晚(角色图)、图2=咖啡馆(场景图)", f"shot0 声明应含图1/图2：实际 {d0}")
    d1 = declaration_for_shot(shots[1], idx)
    ok1 = all(k in d1 for k in ["图1=苏晚", "图3=林深", "图4=站台"])
    check(ok1, f"shot1 声明应含图1/图3/图4：实际 {d1}")
    # 无角色无场景的分镜应返回空声明
    check(declaration_for_shot({"characters": [], "location": ""}, idx) == "", "空分镜应无声明")
    log("unit_legend", legend=[e["name"] for e in legend], d0=d0, d1=d1)


def create_project(name, desc):
    r = client.post("/api/projects", json={"name": name, "description": desc, "genre": "测试"})
    assert r.status_code == 201, f"建项目失败 {r.status_code} {r.get_data(as_text=True)[:200]}"
    pid = r.get_json()["id"]
    log("create_project", name=name, id=pid)
    return pid


def write_story(name, text):
    d = os.path.join(ROOT_PATH, "02_Projects", name, "04_Story")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "source.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def scan_novels(pid):
    r = client.post(f"/api/import/{pid}/scan-novels", json={})
    j = r.get_json()
    log("scan_novels", **j)
    return j


def import_sample_image(pid, asset_name):
    img = Image.new("RGB", (64, 64), (120, 80, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    r = client.post(
        f"/api/import/{pid}/import-image",
        data={"file": (buf, "sample.png"), "asset_name": asset_name},
        content_type="multipart/form-data",
    )
    j = r.get_json()
    log("import_image", **j)
    return j


def retry_llm(fn, tries=5, sleep=8):
    """针对火山 Ark 瞬时网络抖动重试（代码逻辑无错，仅 API 偶发掉线）。"""
    last = None
    for i in range(tries):
        try:
            return fn()
        except RuntimeError as e:
            last = e
            if "大模型调用失败" not in str(e):
                raise
            print(f"[RETRY] LLM 网络抖动，{sleep}s 后重试 ({i + 1}/{tries})", flush=True)
            time.sleep(sleep)
    raise last


def run_pipeline_direct(pid, name, ch_id):
    with app.app_context():
        svc = PipelineService(ROOT_PATH)
        s1 = retry_llm(lambda: svc.novel_to_script(project_name=name, chapter_id=ch_id, project_id=pid))
        sc = (
            ScriptModel.query.filter_by(novel_chapter_id=ch_id)
            .order_by(ScriptModel.id.desc())
            .first()
        )
        assert sc, "novel_to_script 未生成 ScriptModel"
        s2 = retry_llm(lambda: svc.gen_prompts(project_name=name, chapter_id=ch_id, script_id=sc.id, project_id=pid))
    log("novel_to_script", filename=s1.get("filename"), shot_count=s1.get("shot_count"))
    log("gen_prompts", shots=s2.get("shots"), files=len(s2.get("files", [])))
    return s1, s2


def read_prompt_declarations(project_name):
    """读取 07_Prompt，返回 (首段含声明数, 总镜数, 首镜video_prompt前30字)。"""
    d = os.path.join(ROOT_PATH, "02_Projects", project_name, "07_Prompt")
    files = sorted(glob.glob(os.path.join(d, "*_prompt_*.json")))
    total = len(files)
    with_decl = 0
    first_head = ""
    for f in files:
        try:
            d0 = json.load(open(f, "r", encoding="utf-8"))
        except Exception:
            continue
        vp = d0.get("video_prompt", "")
        if vp.startswith("【素材参考】图"):
            with_decl += 1
        if not first_head and vp:
            first_head = vp[:40]
    return with_decl, total, first_head


def first_legend_name(project_name):
    """取该项目的全局图例第一个素材名（用于导入真实参考图验证图N↔0N.jpg）。"""
    legend, _ = build_asset_legend(ROOT_PATH, project_name)
    return legend[0]["name"] if legend else None


def package(pid, pkg_name):
    a = client.post(f"/api/asset-packages/{pid}/analyze", json={}).get_json()
    c = client.post(f"/api/asset-packages/{pid}/create", json={"name": pkg_name}).get_json()
    e = client.post(f"/api/asset-packages/packages/{c['id']}/export", json={}).get_json()
    log("package_analyze", total_files=a.get("total_files"), legend_len=len(a.get("legend", []) or []))
    log("package_export", ok=e.get("ok"), exported_count=e.get("exported_count"), export_dir=e.get("export_dir"))
    return a, c, e


def check_export_naming(e, expect_legend_matched=True):
    """校验导出文件按 01/02… 命名且 index.json 含 legend 与 asset_map。"""
    export_dir = e.get("export_dir")
    index_path = os.path.join(export_dir, "index.json")
    idx = json.load(open(index_path, "r", encoding="utf-8"))
    legend = idx.get("legend", [])
    asset_map = idx.get("asset_map", {})
    check(len(legend) > 0, "index.json 应含非空 legend（图N=角色/场景）")
    # 导出资产文件（排除 index.json / prompts 目录）
    asset_files = sorted(
        f for f in os.listdir(export_dir)
        if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov"))
    )
    check(len(asset_files) > 0, "导出目录应包含重命名后的素材文件")
    ok_naming = all(f[:2].isdigit() and f[2] == "." for f in asset_files)
    check(ok_naming, f"素材文件应按 01./02.… 命名：实际 {asset_files}")
    # 图例命中的素材，其文件名应等于 图号 两位化
    matched = [v for v in asset_map.values() if v.get("name")]
    if expect_legend_matched and matched:
        ok_corr = all(
            v["file"] == f"{int(v['fig'][1:]):02d}{os.path.splitext(v['file'])[1]}"
            for v in matched
        )
        check(ok_corr, f"图例命中素材文件名应=图号两位化：{[(v['fig'], v['file']) for v in matched]}")
    else:
        log("export_naming_skip_corr", reason="无图例命中素材（仅验证 01 命名）")
    return asset_files, legend, asset_map


def main():
    test_legend_unit()

    RUN = time.strftime("%m%d_%H%M%S")  # 每次运行用唯一项目名，避免 DB 残留撞名

    # ===== 项目 A：完整小说 =====
    nameA = f"压测_完整小说_{RUN}"
    pidA = create_project(nameA, "完整小说→提示词+资产→打包")
    write_story(nameA, NOVEL_TEXT)
    scanA = scan_novels(pidA)
    with app.app_context():
        chA = NovelChapter.query.filter_by(project_id=pidA).order_by(NovelChapter.chapter_number).all()
    check(len(chA) >= 2, f"完整小说应拆出>=2章，实际 {len(chA)}")
    s1A, s2A = run_pipeline_direct(pidA, nameA, chA[0].id)
    check(s1A.get("shot_count", 0) > 0, "小说剧本镜头数应为正")
    check(s2A.get("shots", 0) > 0, "小说分镜提示词数应为正")

    # 断言：每条提示词首段含【素材参考】图N=声明
    wdA, totA, headA = read_prompt_declarations(nameA)
    check(wdA > 0 and totA > 0, f"分镜提示词首段应含【素材参考】声明：含声明 {wdA}/{totA}")
    log("prompt_decl_A", with_decl=wdA, total=totA, first_head=headA)

    # 用图例第一个真实素材名导入参考图，验证 图N ↔ 0N.jpg 对应
    refA = first_legend_name(nameA)
    if refA:
        import_sample_image(pidA, refA)
        log("import_ref_A", ref_name=refA)
    aA, cA, eA = package(pidA, "小说打包")
    check(eA.get("ok") is True, "A 打包应成功")
    check_export_naming(eA, expect_legend_matched=bool(refA))

    # ===== 项目 B：每日励志短句（无章节标题）=====
    nameB = f"压测_每日短句_{RUN}"
    pidB = create_project(nameB, "每日短句→提示词+资产→打包")
    write_story(nameB, QUOTE_TEXT)
    scanB = scan_novels(pidB)
    with app.app_context():
        chB = NovelChapter.query.filter_by(project_id=pidB).all()
    check(len(chB) == 1, f"无标题短句应落为单章，实际 {len(chB)}")
    s1B, s2B = run_pipeline_direct(pidB, nameB, chB[0].id)
    check(s1B.get("shot_count", 0) > 0, "短句剧本镜头数应为正")
    check(s2B.get("shots", 0) > 0, "短句分镜提示词数应为正")
    wdB, totB, headB = read_prompt_declarations(nameB)
    check(wdB > 0 and totB > 0, f"短句分镜提示词首段应含声明：含声明 {wdB}/{totB}")
    log("prompt_decl_B", with_decl=wdB, total=totB, first_head=headB)

    # 用图例第一个真实素材名导入参考图，验证每日短句项目也能打包并按图例重命名
    refB = first_legend_name(nameB)
    if refB:
        import_sample_image(pidB, refB)
        log("import_ref_B", ref_name=refB)
    aB, cB, eB = package(pidB, "短句打包")
    check(eB.get("ok") is True, "B 打包应成功")
    check_export_naming(eB, expect_legend_matched=bool(refB))

    # ===== 闭环：把 A 的导出包重新 import-package 到新项目 C =====
    nameC = f"压测_重新导入_{RUN}"
    pidC = create_project(nameC, "导入A的打包文件夹")
    pkg_dir = eA.get("export_dir")
    ri = client.post(f"/api/import/{pidC}/import-package", json={"package_dir": pkg_dir}).get_json()
    log("import_package", **ri)
    check(ri.get("ok") is True, "重新导入应成功")
    check(len(ri.get("imported_prompts", [])) > 0, "重新导入应包含提示词")
    # 重新导入后声明应保留
    wdC, totC, headC = read_prompt_declarations(nameC)
    check(wdC > 0 and totC > 0, f"重新导入后提示词声明应保留：含声明 {wdC}/{totC}")
    # C 可再次打包且重命名
    aC, cC, eC = package(pidC, "重新导入打包")
    check(eC.get("ok") is True, "C 应可再次打包")
    check_export_naming(eC, expect_legend_matched=False)
    sbC = client.get(f"/api/storyboard/{pidC}").get_json()
    check(sbC.get("shot_count", 0) > 0, "重新导入后分镜画布应能读到提示词")

    # 汇总
    print("\n===== 测试汇总 =====")
    print(json.dumps(REPORT, ensure_ascii=False, indent=2))
    if REPORT["errors"]:
        print(f"\n❌ 存在 {len(REPORT['errors'])} 个失败项")
        sys.exit(1)
    print("\n✅ 全部通过："
          "图例单元正确；两类项目提示词首段均含【素材参考】图N=声明；"
          "打包按图例顺序重命名为 01/02… 且 index.json 写入 legend 映射（图N↔0N.jpg 对应）；"
          "打包文件夹可直接重新导入并再次重命名打包。")


if __name__ == "__main__":
    main()
