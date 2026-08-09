"""端到端验证三大功能（离线/mock，不耗真实 LLM token 与出图额度）。

针对《末日快递王》(project 21)：
  1) 实体建档进库：POST /entities/<id>/import
  2) 三视图 / 四角度生成：以 mock=1 填充（验证链路；真实环境去掉 mock 即用 LLM）
  3) 一致性锁：对主角开启锁，校验锁定描述由三视图合成
  4) 场景锚接进提示词：POST /entities/<id>/apply-angles（幂等写回 07_Prompt）
  5) Script Doctor 自动体检：直接调用 PipelineService._auto_script_doctor 写库
  6) 断言：库非空、锁描述含三视图、07_Prompt 含【场景设定】、script_doctor_reports 非空
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("AI_DIRECTOR_OFFLINE", "1")
from web import create_app
from web.models.database import db
from web.models.novel_models import NovelCharacter, SceneLibrary, ScriptDoctorReport, WorldSetting
from web.services.pipeline_service import PipelineService
from web.services.script_doctor import analyze_scripts

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PID = 21
PROJ = "末日快递王"

app = create_app()
errors = []

def check(cond, msg):
    print(("✅" if cond else "❌"), msg)
    if not cond:
        errors.append(msg)

with app.app_context():
    # 1) 建档进库（复用路由逻辑）
    from web.routes.entities import import_entities
    with app.test_request_context(json={}):
        r = import_entities(PID)
    imp = r.get_json()
    print("\n[1] 建档进库:", json.dumps(imp, ensure_ascii=False)[:300])
    # 去重：已建档的会进入 skipped；只要库最终非空即说明建档链路可用
    chars = NovelCharacter.query.filter_by(project_id=PID).all()
    scenes = SceneLibrary.query.filter_by(project_id=PID).all()
    check(len(chars) > 0, f"角色库建档非空（现有 {len(chars)} 条；本次新建 {len(imp.get('created_characters', []))} / 跳过 {len(imp.get('skipped_characters', []))}）")
    check(len(scenes) > 0, f"场景库建档非空（现有 {len(scenes)} 条；本次新建 {len(imp.get('created_scenes', []))} / 跳过 {len(imp.get('skipped_scenes', []))}）")

    # 2) 三视图 / 四角度 mock 生成
    from web.routes.entities import generate_three_view, generate_four_angle
    with app.test_request_context(json={"mock": True, "force": True}):
        r1 = generate_three_view(PID)
        r2 = generate_four_angle(PID)
    print("[2] 三视图:", r1.get_json().get("generated"))
    print("    四角度:", r2.get_json().get("generated"))
    check(all((c.three_view_prompt or "").strip() for c in chars), "角色三视图已写入")
    check(all((s.visual_prompt or "").strip() for s in scenes), "场景四角度主视觉锚已写入")

    # 3) 一致性锁：对主角开启，校验锁定描述由三视图合成
    protag = next((c for c in chars if c.role == "主角"), chars[0])
    from web.routes.novel_characters import toggle_character_lock
    with app.test_request_context(json={"consistency_lock": True}):
        r3 = toggle_character_lock(PID, protag.id)
    lp = r3.get_json().get("locked_prompt", "")
    print(f"[3] 主角「{protag.name}」锁定描述前60字: {lp[:60]}")
    check("【" in lp and ("正面" in lp or "front" in lp.lower() or "侧" in lp), "锁定描述由三视图合成（含角度信息）")

    # 4) 场景锚接进提示词
    from web.routes.entities import apply_angles_to_prompts, apply_locks_to_prompts
    with app.test_request_context(json={}):
        r4 = apply_angles_to_prompts(PID)
    app_cnt = r4.get_json().get("applied", 0)
    print(f"[4] 应用场景锚到 {app_cnt} 个分镜提示词")
    # 抽查 07_Prompt 是否含【场景设定】
    pd = os.path.join(ROOT, "02_Projects", PROJ, "07_Prompt")
    hit = 0
    for f in os.listdir(pd):
        if f.endswith(".json"):
            d = json.load(open(os.path.join(pd, f), encoding="utf-8"))
            if "【场景设定" in (d.get("video_prompt") or ""):
                hit += 1
    print(f"    07_Prompt 中含【场景设定】的镜头数: {hit}")
    check(hit > 0, "07_Prompt 已注入【场景设定】场景锚")

    # 4b) 一致性锁接进提示词（零成本写回，与 apply-angles 对称）
    with app.test_request_context(json={}):
        r4b = apply_locks_to_prompts(PID)
    lock_cnt = r4b.get_json().get("applied", 0)
    print(f"[4b] 应用一致性锁到 {lock_cnt} 个分镜提示词（已锁：{r4b.get_json().get('locked')}）")
    lhit = 0
    for f in os.listdir(pd):
        if f.endswith(".json"):
            d = json.load(open(os.path.join(pd, f), encoding="utf-8"))
            if "【角色一致性锁定" in (d.get("video_prompt") or ""):
                lhit += 1
    print(f"    07_Prompt 中含【角色一致性锁定】的镜头数: {lhit}")
    check(lhit > 0, "07_Prompt 已注入【角色一致性锁定】标签")

    # 5) Script Doctor 自动体检写库
    svc = PipelineService(ROOT)
    proj_dir = os.path.join(ROOT, "02_Projects", PROJ)
    sd = os.path.join(proj_dir, "05_Script")
    scripts = [json.load(open(os.path.join(sd, f), encoding="utf-8"))
               for f in os.listdir(sd) if f.endswith(".json")]
    print(f"[5] 对 {len(scripts)} 个剧本跑自动体检…")
    for sc in scripts:
        svc._auto_script_doctor(PID, sc, PROJ)
    reps = ScriptDoctorReport.query.filter_by(project_id=PID).all()
    print(f"    script_doctor_reports 现有 {len(reps)} 条")
    check(len(reps) == len(scripts), "每章体检报告已存档")
    # 验证「未建档」警告已消失（角色都在库了）
    lib = [c.to_dict() for c in NovelCharacter.query.filter_by(project_id=PID).all()]
    rep = analyze_scripts(scripts, lib)
    unbuilt = [i for i in rep["issues"] if "未建档" in i.get("text", "")]
    print(f"    体检「未建档」类问题数: {len(unbuilt)}（应为 0）")
    check(len(unbuilt) == 0, "QA「未建档」警告已清除")

print("\n===== 验证结论 =====")
if errors:
    print(f"❌ 失败 {len(errors)} 项：")
    for e in errors:
        print("  -", e)
    sys.exit(1)
else:
    print("✅ 全部通过：建档 / 三视图·四角度生成 / 一致性锁合成 / 场景锚接进提示词 / 自动体检存档 均工作正常")
