"""P1 演示数据填充：
1) 为演示项目(离线演示项目)建立「陈默」「林婉儿」两个角色并开启一致性锁。
2) 回填现有 07_Prompt/*.json：写入出场角色(characters)与已锁角色(locked_characters)，
   并按锁把锁定描述注入 video_prompt（幂等，不重复追加）。
不调用任何生图/生文接口，零额度消耗。
"""
import os, json, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web import create_app
from web.models.database import db
from web.models.novel_models import NovelCharacter, WorldSetting

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = create_app()

with app.app_context():
    # 找到演示项目
    from web.models.database import ProjectModel
    proj = ProjectModel.query.filter_by(name="离线演示项目").first()
    if not proj:
        print("未找到演示项目，退出")
        sys.exit(1)
    pid = proj.id
    print("项目:", proj.name, "id=", pid)

    # 确保有世界观（NovelCharacter.world_id 非空约束？建表时 world_id 不可为空，默认 0）
    world = WorldSetting.query.filter_by(project_id=pid).first()
    if not world:
        world = WorldSetting(project_id=pid, name="默认世界观")
        db.session.add(world)
        db.session.commit()
        print("已建默认世界观 id=", world.id)

    seeds = [
        {"name": "陈默", "role": "主角", "gender": "男", "age": "约30岁",
         "appearance": "身穿保安制服，寸头，眼神沉静而警觉，身手矫健",
         "visual_prompt": "电影质感，写实风格，亚洲男性，短寸头发型，深色保安制服，冷峻沉静的面容",
         "consistency_lock": True},
        {"name": "林婉儿", "role": "主角", "gender": "女", "age": "约25岁",
         "appearance": "衣着略显凌乱，面容姣好，神情惊恐",
         "visual_prompt": "电影质感，写实风格，亚洲女性，姣好面容，凌乱衣着，惊恐神情",
         "consistency_lock": True},
    ]
    created = []
    for s in seeds:
        existing = NovelCharacter.query.filter_by(project_id=pid, name=s["name"]).first()
        if existing:
            print(f"角色已存在：{s['name']} (id={existing.id})")
            created.append(existing)
            continue
        c = NovelCharacter(
            project_id=pid, world_id=world.id, name=s["name"], role=s["role"],
            gender=s.get("gender", ""), age=s.get("age", ""),
            appearance=s.get("appearance", ""), visual_prompt=s.get("visual_prompt", ""),
            consistency_lock=s.get("consistency_lock", False),
        )
        # 开启锁时自动合成锁定描述
        if c.consistency_lock and not (c.locked_prompt or "").strip():
            parts = [x for x in [c.appearance, c.visual_prompt] if x and x.strip()]
            c.locked_prompt = "；".join(parts)
        db.session.add(c)
        db.session.commit()
        print(f"已建角色：{s['name']} (id={c.id}) locked_prompt={c.locked_prompt[:30]}...")
        created.append(c)

    # 构建锁定映射
    chars = NovelCharacter.query.filter_by(project_id=pid).all()
    locked_map = {}
    for c in chars:
        if c.consistency_lock:
            lp = (c.locked_prompt or "").strip() or "；".join([x for x in [c.appearance, c.visual_prompt] if x and x.strip()])
            if lp:
                locked_map[c.name] = lp
    print("锁定映射:", {k: v[:20] + "..." for k, v in locked_map.items()})

    # 回填 07_Prompt
    prompt_dir = os.path.join(ROOT, "02_Projects", proj.name, "07_Prompt")
    # 剧本顶层角色名集合（用于识别出场角色）
    script_dir = os.path.join(ROOT, "02_Projects", proj.name, "05_Script")
    known_names = set()
    for f in os.listdir(script_dir):
        if f.endswith(".json"):
            try:
                d = json.load(open(os.path.join(script_dir, f), encoding="utf-8"))
                for c in d.get("characters", []) or []:
                    if isinstance(c, dict) and c.get("name"):
                        known_names.add(c["name"])
            except Exception:
                pass
    print("已知角色名:", known_names)

    count = 0
    for pf in sorted(os.listdir(prompt_dir)):
        if not pf.endswith(".json"):
            continue
        path = os.path.join(prompt_dir, pf)
        try:
            shot = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        vp = shot.get("video_prompt", "")
        present = [n for n in known_names if n in vp]
        locked_present = [n for n in present if n in locked_map]
        changed = False
        for n in locked_present:
            tag = f"【角色一致性锁定·{n}】{locked_map[n]}"
            if tag not in vp:
                vp = (vp + "，" + tag) if vp else tag
                changed = True
        shot["video_prompt"] = vp
        shot["characters"] = present
        if locked_present:
            shot["locked_characters"] = locked_present
        json.dump(shot, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        count += 1
        print(f"回填 {pf}: 角色={present} 锁定={locked_present} changed={changed}")
    print(f"共回填 {count} 个提示词文件")
    print("DONE")
