# -*- coding: utf-8 -*-
"""完成第一章 S02 的整体打包：

1. 真实出图：塌陷烂尾楼(场景图) + S02 分镜帧(img2img 保脸用 林一野.png 做参考)
2. 重组 S02 分镜提示词：图例 → 项目设定 → 镜头描述 → 【负面】，并写回 07_Prompt
3. 打包 04_Output/s02_package/：可点击文件夹 + manifest.md + images/ + S02_frame.png

注：主角最终版暂定 v2（08_Image/characters/林一野/v2.png），分镜帧按此版本保脸出图；
   你改选其他版本后，可在 asset_versions 把对应行 is_final 置 1，重跑本脚本即可刷新。
"""
import os, sys, time, shutil, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dotenv
dotenv.load_dotenv()
os.environ["AI_DIRECTOR_OFFLINE"] = "0"

ROOT = os.path.abspath(".")
PROJ = "末日快递王"
PID = 21
PROJ_PATH = os.path.join(ROOT, "02_Projects", PROJ)
PROMPT_DIR = os.path.join(PROJ_PATH, "07_Prompt")
IMAGE_DIR = os.path.join(PROJ_PATH, "08_Image")
PKG = os.path.join(ROOT, "04_Output", "s02_package")
PKG_IMG = os.path.join(PKG, "images")
for d in (PKG, PKG_IMG):
    os.makedirs(d, exist_ok=True)

S02_FILE = os.path.join(PROMPT_DIR, "第1章 最后一单_script_prompt_S02.json")
CANON_CHAR = os.path.join(IMAGE_DIR, "林一野.png")
SCENE_NAME = "塌陷烂尾楼"
SCENE_PATH = os.path.join(IMAGE_DIR, f"{SCENE_NAME}.png")
FRAME_PATH = os.path.join(IMAGE_DIR, "第1章 最后一单_script_prompt_S02.png")

MODELS = os.environ.get("VOLC_IMAGE_MODELS", "").split(",")
IMG_MODEL = MODELS[0] if MODELS else "doubao-seedream-5-0-pro-260628"
API_KEY = os.environ.get("VOLC_API_KEY", "")
NEG = "低质量,模糊,变形,多余的手指,肢体残缺,文字水印,过饱和,卡通风格,3d渲染塑料感,过度平滑,美化滤镜,多人,裁剪"


def gen_text(client, prompt, path, size):
    sizes = [size, "1024x1024"]
    for sz in sizes:
        for attempt in range(5):
            try:
                res = client.generate(prompt, NEG, size=sz, n=1)
            except Exception as e:
                time.sleep(min(2 ** attempt * 4 + 3, 30)); continue
            if isinstance(res, list) and res and res[0]:
                if client.save_b64(res[0], path):
                    return True, sz, None
            elif isinstance(res, str):
                if "429" in res:
                    time.sleep(min(2 ** attempt * 5, 40)); continue
                time.sleep(min(2 ** attempt * 4 + 3, 30)); continue
            else:
                time.sleep(3)
    return False, size, "重试耗尽"


def gen_ref(client, ref_path, prompt, path, size):
    sizes = [size, "1024x1024"]
    for sz in sizes:
        for attempt in range(5):
            try:
                res = client.generate_with_ref([ref_path], prompt, NEG, size=sz, n=1)
            except Exception as e:
                time.sleep(min(2 ** attempt * 4 + 3, 30)); continue
            if isinstance(res, list) and res and res[0]:
                if client.save_b64(res[0], path):
                    return True, sz, None
            elif isinstance(res, str):
                if "429" in res:
                    time.sleep(min(2 ** attempt * 5, 40)); continue
                time.sleep(min(2 ** attempt * 4 + 3, 30)); continue
            else:
                time.sleep(3)
    return False, size, "重试耗尽"


def main():
    from web import create_app
    from web.services.prompt_assembly import build_full_prompt, get_project_globals_dict
    from web.services.image_client import ImageClient
    app = create_app()
    with app.app_context():
        shot = json.load(open(S02_FILE, encoding="utf-8"))
        g = get_project_globals_dict(PID)
        print(f"[1] 加载 S02 | 角色={shot.get('characters')} 场景={shot.get('location')}")
        print(f"    图例: {[a['fig']+'='+a['name']+'('+a['kind']+')' for a in shot.get('asset_refs', [])]}")
        print(f"    全局 art_style: {g.get('art_style','')[:50]}…")

        # 2) 重组 完整提示词
        full_prompt = build_full_prompt(shot, g)
        # 写回 07_Prompt 文件（让存储与打包一致）
        shot["video_prompt"] = full_prompt
        with open(S02_FILE, "w", encoding="utf-8") as f:
            json.dump(shot, f, ensure_ascii=False, indent=2)
        print("[2] ✅ 已按新格式重组 S02 提示词并写回 07_Prompt")
        print("    第一段(开始):", full_prompt.split("\n\n")[0][:80])
        print("    末尾段:", full_prompt.split("\n\n")[-1][:80])

        # 解析主角最终版参考图：优先 asset_versions 中 is_final=1 的林一野
        canon_char = CANON_CHAR
        try:
            import sqlite3 as _sql
            _db = _sql.connect("04_Output/ai_video_data.db")
            _row = _db.execute(
                "SELECT content FROM asset_versions WHERE project_id=? AND asset_key=? AND is_final=1 LIMIT 1",
                (PID, "林一野"),
            ).fetchone()
            _db.close()
            if _row and _row[0]:
                _cand = _row[0]
                if not os.path.isabs(_cand):
                    _cand = os.path.join(PROJ_PATH, _cand)
                if os.path.exists(_cand):
                    canon_char = _cand
                    print(f"[*] 主角最终版参考(v2): {canon_char}")
                else:
                    print(f"[*] 最终版文件不存在: {_cand}，回退到 {CANON_CHAR}")
            else:
                print(f"[*] 未找到 is_final 版本，回退到 {CANON_CHAR}")
        except Exception as e:
            print(f"[*] 读取最终版失败，回退到 {CANON_CHAR}: {e}")

        client = ImageClient(api_key=API_KEY, model=IMG_MODEL)

        # 3) 生成 塌陷烂尾楼 场景图
        scene_prompt = (
            "末日废土塌陷烂尾楼环境概念图：半塌的十几层混凝土框架结构，裸露钢筋与碎砖散落，"
            "墙面斑驳渗水，画满涂鸦与褪色广告，碎玻璃与灰尘在阴天冷光中弥漫。"
            "低饱和度青灰冷调，苍凉压抑氛围；广角远景，无人物，电影感氛围；无文字无边框。"
        )
        if os.path.exists(SCENE_PATH):
            print(f"[3] 已有场景图: {SCENE_PATH}（跳过生成）")
        else:
            print("[3] 出图 塌陷烂尾楼 场景 (1344x768)…")
            ok, sz, err = gen_text(client, scene_prompt, SCENE_PATH, "1344x768")
            print(f"    {'✅' if ok else '❌'} 塌陷烂尾楼 [{sz}] {'' if ok else err}")

        # 4) 生成 S02 分镜帧（img2img 保脸）
        # 从 full_prompt 提取"镜头描述"段（去掉【项目设定】后到【负面】前）
        scene_only = full_prompt
        for marker in ["【项目设定】", "【负面】"]:
            if marker in scene_only:
                scene_only = scene_only.split(marker)[0]
        scene_only = scene_only.replace("【素材参考】" + (scene_only.split("【素材参考】")[1].split("\n\n")[0]), "").strip()
        # 上面处理略复杂，简化为：直接用 shot 原 video_prompt 去掉【素材参考】首段
        orig_vp = shot["video_prompt"]
        # 我们的重组后 full_prompt 格式：legend + global + 旧的原始 scene_text + negative
        # 旧的原始 scene_text 是 build_full_prompt 内部保留的 part。直接用 full_prompt 中
        # 【项目设定】之后、 【负面】之前的内容。
        try:
            scene_text = full_prompt.split("【项目设定】", 1)[1].split("【负面】", 1)[0].strip()
        except Exception:
            scene_text = orig_vp
        frame_prompt = (
            "末日废土电影级帧：林一野（保持参考图人物身份，高眉骨、深眼窝、身穿袖口短一截的旧夹克）"
            "站在半塌烂尾楼边缘，全景俯拍，他深吸一口气闭眼跳下，砸进下方一堆发馊的快递纸箱中，"
            "左腿磕到钢筋，龇牙咧嘴瘸着腿往外爬；白天灰蒙蒙的天空，废土建筑残骸，尘土飞扬，低饱和度冷调。"
            f"核心动作：{scene_text[:200]}"
        )
        if os.path.exists(FRAME_PATH):
            print(f"[4] 已有 S02 分镜帧: {FRAME_PATH}（跳过生成）")
        else:
            print("[4] 出图 S02 分镜帧 (img2img 保脸, 1344x768)…")
            ok, sz, err = gen_ref(client, canon_char, frame_prompt, FRAME_PATH, "1344x768")
            print(f"    {'✅' if ok else '❌'} S02_frame [{sz}] {'' if ok else err}")

        # 5) 打包：复制素材到 images/（用图号命名）
        assets_to_copy = []
        for ar in shot.get("asset_refs", []):
            fig = ar["fig"]; name = ar["name"]
            # 原图位置
            if ar["kind"] == "角色":
                src = os.path.join(IMAGE_DIR, f"{name}.png")
            else:
                src = os.path.join(IMAGE_DIR, f"{name}.png")
            fig_no = int(fig.replace("图", ""))
            dst_name = f"{fig}_{name}.png"
            dst = os.path.join(PKG_IMG, dst_name)
            if os.path.exists(src):
                shutil.copy(src, dst)
                assets_to_copy.append((fig, name, ar["kind"], dst_name))
                print(f"   📎 {fig}={name} → {dst_name}")
            else:
                print(f"   ⚠ 缺素材图: {src}")

        # 复制分镜帧
        if os.path.exists(FRAME_PATH):
            shutil.copy(FRAME_PATH, os.path.join(PKG, "S02_frame.png"))
            print(f"   📎 S02_frame.png (完整分镜帧)")

        # 6) 生成 manifest.md
        manifest = []
        manifest.append("# S02 打包清单 · 第一章 第2镜\n")
        manifest.append("> 打包内容：分镜关键词 + 本镜所需素材图1-图N + 完整重组后的分镜提示词（含负面词）\n")
        manifest.append(f"> 主角最终版：v2（{canon_char}）已选定，分镜帧按此版本保脸出图\n")
        manifest.append("## 一、分镜关键词\n")
        # 提取"镜头描述"段（项目设定之后、负面之前）
        manifest.append("```\n" + scene_text + "\n```\n")
        manifest.append("\n## 二、本镜所需素材（点击 images/ 文件夹查看）\n")
        manifest.append("| 图号 | 类型 | 名称 | 文件 |")
        manifest.append("| :--- | :--- | :--- | :--- |")
        for fig, name, kind, fn in assets_to_copy:
            manifest.append(f"| {fig} | {kind} | {name} | images/{fn} |")
        if os.path.exists(FRAME_PATH):
            manifest.append(f"| — | 分镜帧 | S02_frame | S02_frame.png |")
        manifest.append("\n## 三、完整分镜提示词（按约定格式重组）\n")
        manifest.append("> 顺序：①【素材参考】图N=XX → ②【项目设定】画风/色调/渲染/人物音色 → ③ 镜头描述 → ④【负面】\n")
        manifest.append("```text\n" + full_prompt + "\n```\n")
        manifest.append("\n## 四、负面词（末尾）\n")
        manifest.append("- 镜级：" + (shot.get("negative_prompt", "") or "—"))
        manifest.append("- 项目级：" + (g.get("negative_prompts", "") or "—"))
        with open(os.path.join(PKG, "manifest.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(manifest))
        print("\n[6] ✅ manifest.md 已生成")

        # 7) 单独一份完整提示词文件，便于复制
        with open(os.path.join(PKG, "完整提示词.md"), "w", encoding="utf-8") as f:
            f.write("# S02 完整提示词（可直接复制给视频模型）\n\n```text\n" + full_prompt + "\n```\n")
        print("[7] ✅ 完整提示词.md 已生成")

        print("\n=== 打包完成 ===")
        print(f"📂 打开: {PKG}")
        for f in os.listdir(PKG):
            print(f"   - {f}/")
        if os.path.exists(PKG_IMG):
            for f in os.listdir(PKG_IMG):
                print(f"     └── images/{f}")


if __name__ == "__main__":
    main()
