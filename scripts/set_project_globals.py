"""填充《末日快递王》项目级全局提示词（画风/色调/渲染/人物音色/negative）。

幂等：重复运行只覆盖 __globals__，不破坏其它配置。
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dotenv
dotenv.load_dotenv()
os.environ["AI_DIRECTOR_OFFLINE"] = "0"

from web import create_app
from web.models.database import db, ProjectConfig

PID = 21

GLOBALS = {
    # 视觉风格
    "art_style": "末日废土写实插画风，电影级叙事镜头，带纪实摄影的粗粝颗粒感与胶片质感，构图参考末日题材影视",
    "color_palette": "低饱和冷青灰主调，阴天与夜景偏蓝绿；火光、车灯、警报点缀暖橙，制造冷暖对比",
    "lighting": "自然漫射天光为主，偶发体积光与丁达尔效应，硬侧光刻画废墟轮廓与人物骨骼",
    "mood": "苍凉、压抑中带荒诞与求生张力",
    # 渲染与质感（整体 positive，注入每镜末尾之前）
    "positive_prompts": "Unreal Engine 5 写实渲染，8k 细节，电影级构图，浅景深虚化，体积雾与尘埃，做旧金属与龟裂混凝土质感，皮肤毛孔级纹理，胶片颗粒",
    # 负面（整体，注入每镜末尾）
    "negative_prompts": "低质量,模糊,变形,多余的手指,肢体残缺,文字水印,过饱和,卡通风格,3d 渲染塑料感,过度平滑,美化滤镜",
    # 人物音色（按角色名索引，仅本镜出场角色会写入提示词）
    "character_voices": {
        "林一野": "低沉沙哑、语速偏慢、带废土痞气与疲惫感的成熟男声",
        "阿禾": "清亮略带颤抖的少女声，语气倔强",
        "林父": "苍老浑浊、断续的男声",
        "林母": "温吞软糯、欲言又止的中年女声",
    },
}


def main():
    app = create_app()
    with app.app_context():
        cfg = ProjectConfig.query.filter_by(project_id=PID).first()
        if not cfg:
            cfg = ProjectConfig(project_id=PID)
            db.session.add(cfg)
        prompts = json.loads(cfg.system_prompts) if cfg.system_prompts else {}
        prompts["__globals__"] = GLOBALS
        cfg.system_prompts = json.dumps(prompts, ensure_ascii=False)
        db.session.commit()
        print(f"✅ 项目 {PID} 全局提示词已写入：")
        for k in ("art_style", "color_palette", "lighting", "mood",
                  "positive_prompts", "negative_prompts", "character_voices"):
            v = GLOBALS[k]
            if isinstance(v, dict):
                print(f"  {k}: {len(v)} 个角色音色")
            else:
                print(f"  {k}: {str(v)[:50]}…")


if __name__ == "__main__":
    main()
