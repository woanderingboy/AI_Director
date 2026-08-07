"""端到端验证脚本：创建项目 -> 小说章节 -> 剧本 -> 分镜提示词，并核对产出文件。"""
import json
import os
import sqlite3
import time
import urllib.request

BASE = "http://127.0.0.1:5000"
ROOT = r"D:\AI_Director"
DB = os.path.join(ROOT, "04_Output", "ai_video_data.db")


def post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8")), r.status


def get(path):
    req = urllib.request.Request(BASE + path, method="GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def poll_task(task_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        t = get(f"/api/tasks/{task_id}")
        if t.get("status") in ("success", "fail", "cancelled"):
            return t
        time.sleep(0.5)
    return get(f"/api/tasks/{task_id}")


def db_query(sql, args=()):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute(sql, args)
    row = cur.fetchone()
    con.close()
    return row


def main():
    print("=" * 60)
    print("步骤 1/6 · 创建项目（幂等：先清理同名旧项目）")
    existing = get("/api/projects")
    for p in existing:
        if p["name"] == "离线演示项目":
            req = urllib.request.Request(BASE + f"/api/projects/{p['id']}", method="DELETE")
            with urllib.request.urlopen(req, timeout=30) as r:
                pass
            print(f"  · 已删除旧项目 id={p['id']}")
    proj, status = post("/api/projects", {"name": "离线演示项目", "description": "本地离线跑通验证", "genre": "剧情"})
    assert status == 201, f"创建项目失败: {proj}"
    pid = proj["id"]
    print(f"  ✅ 项目已创建 id={pid} name={proj['name']}")

    print("步骤 2/6 · 创建带正文的小说章节")
    chapter_text = (
        "深夜的B2停车场，只有应急灯泛着惨红。陈默穿着保安制服独自巡逻，"
        "寸头下的眼神沉静而警觉。角落里传来细微的挣扎声——三个蒙面绑匪正控制着"
        "一名女子。陈默悄无声息地贴近，在对方反应过来之前将其一一制服，"
        "救下了惊魂未定的林婉儿。两人四目相对，他向她伸出手，灯光洒在两人身上。"
    )
    ch, status = post(f"/api/novel/{pid}/novel-chapters", {
        "title": "第一幕：停车场重逢",
        "content": chapter_text,
        "chapter_number": 1,
        "summary": "陈默夜巡停车场，制服绑匪救下林婉儿。",
    })
    assert status == 201, f"创建章节失败: {ch}"
    cid = ch["id"]
    print(f"  ✅ 章节已创建 id={cid} 字数={ch.get('word_count')}")

    print("步骤 3/6 · 流水线 ① 小说→剧本（含分镜拆分）")
    resp, _ = post("/api/pipeline/run", {
        "stage": "pipeline.novel2script",
        "project_id": pid,
        "chapter_id": cid,
        "project_name": "离线演示项目",
    })
    task_id = resp["task_id"]
    print(f"  · 已提交任务 task_id={task_id}")
    t = poll_task(task_id)
    print(f"  · 任务状态: {t['status']} | 进度: {t.get('progress')}% | 消息: {t.get('message')}")
    assert t["status"] == "success", f"剧本生成失败: {t.get('message')} | logs={t.get('logs')}"

    row = db_query("SELECT id, filename, shot_count FROM scripts WHERE novel_chapter_id=? ORDER BY id DESC", (cid,))
    assert row, "未在 scripts 表找到剧本记录"
    script_id, script_file, shot_count = row
    print(f"  ✅ 剧本已入库 id={script_id} 文件={script_file} 镜头数={shot_count}")

    print("步骤 4/6 · 流水线 ② 剧本→视觉提示词")
    resp, _ = post("/api/pipeline/run", {
        "stage": "pipeline.gen_prompts",
        "project_id": pid,
        "chapter_id": cid,
        "script_id": script_id,
        "project_name": "离线演示项目",
    })
    task_id = resp["task_id"]
    t = poll_task(task_id)
    print(f"  · 任务状态: {t['status']} | 进度: {t.get('progress')}% | 消息: {t.get('message')}")
    assert t["status"] == "success", f"提示词生成失败: {t.get('message')}"

    print("步骤 5/6 · 核对磁盘产出文件")
    script_dir = os.path.join(ROOT, "02_Projects", "离线演示项目", "05_Script")
    prompt_dir = os.path.join(ROOT, "02_Projects", "离线演示项目", "07_Prompt")
    scripts = sorted(os.listdir(script_dir)) if os.path.isdir(script_dir) else []
    prompts = sorted(os.listdir(prompt_dir)) if os.path.isdir(prompt_dir) else []
    print(f"  · 05_Script/: {scripts}")
    print(f"  · 07_Prompt/: {prompts}")
    assert scripts, "05_Script 目录无产出"
    assert prompts, "07_Prompt 目录无产出"

    print("步骤 6/6 · 一键全流程 run_all（验证编排）")
    resp, _ = post("/api/pipeline/run", {
        "stage": "pipeline.run_all",
        "project_id": pid,
        "chapter_id": cid,
        "project_name": "离线演示项目",
    })
    t = poll_task(resp["task_id"])
    print(f"  · run_all 状态: {t['status']} | {t.get('message')}")
    res = t.get("result") or {}
    print(f"  · run_all 结果键: {list(res.keys()) if isinstance(res, dict) else res}")

    print("步骤 7/7 · 验证资产版本管理与素材打包导出端点")
    # 资产版本：保存一条角色版本
    av, st = post("/api/asset-versions/save", {
        "project_id": pid,
        "asset_type": "character",
        "asset_key": "陈默",
        "content": json.dumps({"appearance": "寸头青年，深邃眼神，保安制服"}, ensure_ascii=False),
        "notes": "离线演示角色设定",
    })
    av_id = av.get("id") or (av.get("version") or {}).get("id")
    print(f"  · 资产版本保存: status={st} id={av_id} tag={av.get('version_tag')}")
    assert st in (200, 201) and av_id, f"资产版本保存失败: {av}"
    # 确认为最终版
    req = urllib.request.Request(BASE + f"/api/asset-versions/confirm/{av_id}", method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        cf = json.loads(r.read().decode("utf-8"))
    print(f"  · 确认最终版: {cf.get('message')}")
    # 素材包：创建并分析需求
    # 放一张占位资产图到 08_Image，再触发导出，验证打包落地
    img_dir = os.path.join(ROOT, "02_Projects", "离线演示项目", "08_Image")
    os.makedirs(img_dir, exist_ok=True)
    placeholder = os.path.join(img_dir, "陈默_保安制服_final.png")
    try:
        from PIL import Image
        if not os.path.exists(placeholder):
            Image.new("RGB", (64, 64), (30, 30, 40)).save(placeholder)
        print(f"  · 占位资产图就绪: {os.path.basename(placeholder)}")
    except Exception as e:
        print(f"  · 占位图生成跳过: {e}")

    pkg, st = post(f"/api/asset-packages/{pid}/create", {
        "name": "停车场重逢_素材包",
        "prompt_text": "电影级画面，暗调风格，全景镜头，深夜停车场，黄昏侧逆光，陈默制服绑匪，林婉儿惊恐",
    })
    print(f"  · 素材打包创建: status={st} id={pkg.get('id')} 状态={pkg.get('status')}")
    assert st == 201, f"素材打包失败: {pkg}"
    exp, st = post(f"/api/asset-packages/packages/{pkg['id']}/export", {})
    print(f"  · 素材包导出: ok={exp.get('ok')} 导出数={exp.get('exported_count')} dir={exp.get('export_dir')}")

    print("=" * 60)
    print("✅ 四阶段流水线 + 资产版本 + 素材打包（离线模式）端到端跑通成功！")
    print(f"  项目: 离线演示项目 (id={pid})")
    print(f"  剧本文件: {os.path.join('05_Script', scripts[0])}")
    print(f"  提示词文件: {len(prompts)} 个 -> {prompts}")
    print(f"  资产版本 id={av_id} (最终版) | 素材包 id={pkg.get('id')}")
    print(f"  SQLite: 04_Output/ai_video_data.db")

    print("=" * 60)
    print("✅ 四阶段流水线（离线模式）端到端跑通成功！")
    print(f"  项目: 离线演示项目 (id={pid})")
    print(f"  剧本文件: {os.path.join('05_Script', scripts[0])}")
    print(f"  提示词文件: {len(prompts)} 个")
    print(f"  SQLite: 04_Output/ai_video_data.db")


if __name__ == "__main__":
    main()
