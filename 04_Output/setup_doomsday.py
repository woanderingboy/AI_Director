# -*- coding: utf-8 -*-
"""末日女子生存指南 · 真实项目建置 + 四阶段流水线跑通（英雄路径）"""
import sys, os, json, time
sys.path.insert(0, "D:/AI_Director")

from web import create_app
from web.models.database import (
    db, ProjectModel, ChapterModel, ScriptModel, ProjectConfig,
)
from web.models.novel_models import NovelCharacter, WorldSetting
from web.services.pipeline_service import PipelineService

NOVEL = """【剧名】末日女子生存指南
【类型】末日 / 生存 / 漫剧（竖屏短剧）
【主角】苏晚，28岁，前急诊科护士——病毒爆发后被逼成了江城最利落的“活人”。

━━━━━━━━━━ 第47天·别做那个好人 ━━━━━━━━━━

【引子 · 苏晚画外音】
这是我的生存指南。病毒带走了百分之九十的人，剩下的人里，一半变成了怪物，另一半变成了比怪物更糟的东西。我叫苏晚，曾经是急诊科护士。现在？现在我只是个还没死的人。
指南第一条——善良，是末日里最贵的奢侈品，你负担不起。

江城，沦陷第四十七天。

雨水把整条解放路泡成了墨绿色。苏晚踩着及踝的积水，医用口罩上方那双眼睛冷得像手术刀。她背着的不是急救箱，是一个塞满抗生素和绷带的登山包。

“姐，前面……前面是不是有人？”林小满揪着苏晚的衣角，声音发抖。这个十九岁的姑娘是苏晚三天前在便利店救下的，到现在还不敢一个人上厕所。

苏晚抬手，示意她闭嘴。巷口的阴影里，一个穿快递服的男人正把头埋进一只翻倒的垃圾桶。他动作太规律了——规律得不像活人。

“别看。走。”苏晚拽着林小满往后退。

可还是晚了。快递员抬起头，半张脸已经灰白溃烂，眼眶里爬着东西。他没有扑过来，只是歪着头，发出那种喉咙被水泡过的咕噜声。

苏晚没有犹豫。她从腰后抽出早就改装的消防斧——急诊科教会她救人，末日教会她砍人。一斧劈在对方膝弯，趁它倒地的瞬间，第二下精准地砸向颈侧。

【苏晚画外音】
指南第二条——善良留给同类，斧头留给异类。你犹豫的那半秒，够它咬穿你的颈动脉。

老周在街角等他们。这个曾经的消防队长如今满身油烟味，守着一辆改装三轮，车斗里堆着罐头和孩子玩具。“又砍了几个？”他头也不抬，“你这护士，比我们当年出警还利索。”

“少废话，油呢？”苏晚把林小满塞上车。

“加油站早空了。但我找到个好东西——”老周掀开油布，露出一台还能用的发电机和半箱柴油，“够咱们撑到江对岸的避难所。”

林小满突然指着天空：“那、那是什么？”

远处，三架涂着红十字的无人机正掠过江面，投下成串的照明弹。那是官方撤离的信号，也是所有幸存者都心知肚明的秘密——信号出现的夜晚，溃兵和劫匪，会比丧尸来得更快。

【苏晚画外音】
指南第三条——看见救援，先跑。因为想抢你最后一口粮的人，永远比想救你的人来得快。

苏晚把斧头别回腰后，发动三轮：“坐稳。这趟，我们不当好人，我们只当活人。”

雨幕里，三个身影冲向江边的渡口。身后的城市，正一盏一盏地熄灭。

【本章指南小结】
一、善良留给同类，斧头留给异类。
二、看见救援先跑——抢粮的永远比救人的快。
三、活下来不是靠运气，是靠不心软。
"""

CHARACTERS = [
    {
        "name": "苏晚",
        "role": "女主 / 叙述者",
        "gender": "女",
        "age": 28,
        "appearance": "冷白肤色，黑色长直发，常戴医用口罩，穿改制军绿冲锋衣，身形瘦削挺拔，眼神冷静锐利如手术刀",
        "visual_prompt": "realistic cinematic, pale cold skin, long straight black hair, medical mask, modified military-green windbreaker, slender upright figure, sharp calm eyes",
        "personality": "冷静、果决、毒舌但护短",
        "background": "前急诊科护士，病毒爆发后独自生存47天",
        "locked_prompt": "",  # 留空 -> 由 appearance+visual_prompt 自动合成
    },
    {
        "name": "林小满",
        "role": "被庇护者",
        "gender": "女",
        "age": 19,
        "appearance": "齐肩栗色卷发，圆脸杏眼，鹅黄色连帽卫衣",
        "visual_prompt": "realistic, shoulder-length chestnut wavy hair, round face, almond eyes, yellow hoodie",
        "personality": "怯懦、依赖、逐渐成长",
        "background": "大学生，被苏晚在便利店救下",
        "locked_prompt": "十九岁少女，齐肩栗色卷发，圆脸杏眼，鹅黄色连帽卫衣，神情怯懦依赖",
    },
    {
        "name": "老周",
        "role": "盟友",
        "gender": "男",
        "age": 52,
        "appearance": "寸头灰白短发，方脸，左颊有旧烧伤疤痕，深蓝工装，体格壮硕",
        "visual_prompt": "realistic, buzz-cut grey hair, square face, old burn scar on left cheek, dark-blue workwear, burly",
        "personality": "粗粝、可靠、黑色幽默",
        "background": "前消防队长",
        "locked_prompt": "",  # 留空 -> 自动合成
    },
]


def main():
    app = create_app()
    with app.app_context():
        # 1) 项目（幂等）
        proj = ProjectModel.query.filter_by(name="末日女子生存指南").first()
        if not proj:
            proj = ProjectModel(
                name="末日女子生存指南",
                description="末日生存漫剧 · 苏晚的活人指南",
                genre="末日/生存/漫剧",
            )
            db.session.add(proj)
            db.session.commit()
            print(f"[建项目] 新建 id={proj.id} name={proj.name}")
        else:
            print(f"[建项目] 已存在 id={proj.id}，复用")

        pid = proj.id

        # 2) ProjectConfig -> 指向真实 volcengine LLM（否则会走离线 mock）
        pc = ProjectConfig.query.filter_by(project_id=pid).first()
        if not pc:
            pc = ProjectConfig(project_id=pid)
            db.session.add(pc)
        pc.provider_key = "volcengine"
        pc.model = "glm-5-2-260617"
        pc.temperature = 0.75
        pc.max_tokens = 4096
        db.session.commit()
        print(f"[配置] provider={pc.provider_key} model={pc.model}（真实 LLM）")

        # 3) 小说章节（幂等：同标题不重复建）
        chap = ChapterModel.query.filter_by(project_id=pid, title="第47天·别做那个好人").first()
        if not chap:
            chap = ChapterModel(
                project_id=pid,
                title="第47天·别做那个好人",
                filename="第47天·别做那个好人.txt",
                content=NOVEL,
            )
            db.session.add(chap)
            db.session.commit()
            print(f"[小说] 新建章节 id={chap.id}")
        else:
            print(f"[小说] 章节已存在 id={chap.id}，复用")

        # 4) 世界观（角色 world_id 必填 FK）+ 角色 + 一致性锁（幂等）
        world = WorldSetting.query.filter_by(project_id=pid).first()
        if not world:
            world = WorldSetting(
                project_id=pid,
                name="末日江城世界观",
                world_type="近未来废土",
                era="病毒爆发第47天",
                geography="江城——一座被洪水与废墟吞没的沿江城市",
                rules="善良留给同类，斧头留给异类；看见救援先跑；活下来靠不心软",
            )
            db.session.add(world)
            db.session.commit()
            print(f"[世界观] 新建 id={world.id}")
        else:
            print(f"[世界观] 已存在 id={world.id}，复用")

        wid = world.id
        for c in CHARACTERS:
            exist = NovelCharacter.query.filter_by(project_id=pid, name=c["name"]).first()
            if not exist:
                exist = NovelCharacter(project_id=pid, world_id=wid, name=c["name"])
                db.session.add(exist)
            exist.world_id = wid
            exist.role = c["role"]
            exist.gender = c["gender"]
            exist.age = c["age"]
            exist.appearance = c["appearance"]
            exist.visual_prompt = c["visual_prompt"]
            exist.personality = c["personality"]
            exist.background = c["background"]
            exist.consistency_lock = True
            exist.locked_prompt = c["locked_prompt"]
        db.session.commit()
        print(f"[角色] 已建/更新 {len(CHARACTERS)} 个角色（一致性锁开启）")

        # 5) 四阶段流水线
        ps = PipelineService("D:/AI_Director")
        report = {}

        print("\n=== 阶段一：小说→剧本 ===")
        t0 = time.time()
        try:
            r1 = ps.novel_to_script(project_name=proj.name, chapter_id=chap.id, project_id=pid)
            report["script"] = r1
            print(f"  OK 镜头数={r1['shot_count']} 总时长={r1['total_duration']}s 文件={r1['filename']} ({round(time.time()-t0,1)}s)")
        except Exception as e:
            import traceback; traceback.print_exc()
            report["script"] = {"error": str(e)}

        if "error" not in report["script"]:
            script = ScriptModel.query.filter_by(chapter_id=chap.id).order_by(ScriptModel.id.desc()).first()
            print("\n=== 阶段二：剧本→提示词 ===")
            t0 = time.time()
            try:
                r2 = ps.gen_prompts(project_name=proj.name, chapter_id=chap.id, script_id=script.id, project_id=pid)
                report["prompts"] = r2
                print(f"  OK 提示词数={r2['shots']} ({round(time.time()-t0,1)}s)")
            except Exception as e:
                import traceback; traceback.print_exc()
                report["prompts"] = {"error": str(e)}

            print("\n=== 阶段三：提示词→图片（真实 Seedream）===")
            t0 = time.time()
            try:
                r3 = ps.draw_images(project_id=pid, project_name=proj.name)
                report["images"] = r3
                print(f"  OK 状态={r3.get('status')} 模型={r3.get('model')} 数量={r3.get('count')} ({round(time.time()-t0,1)}s)")
            except Exception as e:
                import traceback; traceback.print_exc()
                report["images"] = {"error": str(e)}

            print("\n=== 阶段四：图片→视频（本地 moviepy）===")
            t0 = time.time()
            try:
                r4 = ps.render_videos(project_id=pid, project_name=proj.name)
                report["videos"] = r4
                print(f"  OK 状态={r4.get('status')} 视频={r4.get('video')} 镜头={r4.get('count')} 带锁={r4.get('locked_shot_count')} ({round(time.time()-t0,1)}s)")
            except Exception as e:
                import traceback; traceback.print_exc()
                report["videos"] = {"error": str(e)}

        print("\n=== 汇总 ===")
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
