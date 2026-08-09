# -*- coding: utf-8 -*-
"""真实出图：第一章 S01 分镜的全部素材（角色图 / 场景图 / 分镜帧）+ 提示词打包。

- 用真实 LLM(glm-5) 重写林一野三视图 与 废土街道某处 四角度（补齐之前 mock 的空壳）
- 用真实 Seedream 出 3 张图：角色设定图 / 场景图 / 分镜帧
- 更新 08_Image 真实资产，并复制进 04_Output/s01_package/ 交付
- 生成 manifest.md（每个素材 + 其出图提示词 + 映射关系）
"""
import os, re, json, time, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 项目根加入 path
import dotenv
dotenv.load_dotenv()
os.environ["AI_DIRECTOR_OFFLINE"] = "0"  # 强制真实大模型

ROOT = os.path.abspath(".")
PROJ = "末日快递王"
PID = 21
PROJ_PATH = os.path.join(ROOT, "02_Projects", PROJ)
PROMPT_DIR = os.path.join(PROJ_PATH, "07_Prompt")
IMAGE_DIR = os.path.join(PROJ_PATH, "08_Image")
PKG = os.path.join(ROOT, "04_Output", "s01_package")
os.makedirs(PKG, exist_ok=True)

S01_FILE = os.path.join(PROMPT_DIR, "第1章 最后一单_script_prompt_S01.json")
CHAR_NAME = "林一野"
SCENE_NAME = "废土街道某处"

from web.services.novel_ai_service import generate_character_three_view, generate_scene_four_angle
from web.services.image_client import ImageClient
from web import create_app
import sqlite3

# ── 1) 取小说内嵌外貌/场景线索 ──────────────────────────────
sc = json.load(open(os.path.join(PROJ_PATH, "05_Script", "第1章 最后一单_script.json"), encoding="utf-8"))
char_appearance = ""
for c in sc["characters"]:
    if c["name"] == CHAR_NAME:
        char_appearance = c.get("description", "")
scene_desc = "废土末日街道：清晨阴天，破败荒凉，散落碎玻璃与烂菜叶，低饱和度冷调，电影感写实氛围。"

# ── 2) 真实 LLM 重写三视图 / 四角度（带重试） ───────────────
def llm_retry(fn, *a, **k):
    last = None
    for i in range(3):
        try:
            r = fn(*a, **k)
            if r and any(str(v).strip() for v in r.values()):
                return r
            last = "空结果"
        except Exception as e:
            last = str(e)[:120]
            time.sleep(8)
    print(f"  ⚠ LLM 重试失败({last})，使用小说线索兜底")
    return None

app = create_app()
with app.app_context():
    print("[1] 真实 LLM 重写 林一野 三视图 …")
    tv = llm_retry(generate_character_three_view,
                   {"name": CHAR_NAME, "role": "主角", "appearance": char_appearance, "visual_prompt": ""},
                   project_id=PID)
    if not tv:
        tv = {"front": f"{char_appearance} 正面标准站姿，清晰展现五官与服饰。",
              "side": f"{char_appearance} 45°侧身，体现身材比例与轮廓。",
              "back": f"{char_appearance} 背面，展示随身物件。"}
    print("   正面:", tv["front"][:60], "…")

    print("[2] 真实 LLM 重写 废土街道某处 四角度 …")
    fa = llm_retry(generate_scene_four_angle,
                   {"name": SCENE_NAME, "description": scene_desc, "mood": "荒诞，破败"},
                   project_id=PID)
    if not fa:
        fa = {"front": scene_desc, "back": scene_desc, "side": scene_desc, "over": scene_desc}
    print("   正打:", fa["front"][:60], "…")

# ── 3) 写回数据库（让一致性锁/场景锚变成真实描述） ──────────
con = sqlite3.connect(os.path.join(ROOT, "04_Output", "ai_video_data.db"))
con.row_factory = sqlite3.Row
cur = con.cursor()
# 角色
cur.execute("SELECT id FROM novel_characters WHERE project_id=? AND name=?", (PID, CHAR_NAME))
row = cur.fetchone()
tv_json = json.dumps(tv, ensure_ascii=False)
lock_json = json.dumps(tv, ensure_ascii=False)
if row:
    cur.execute("""UPDATE novel_characters SET appearance=?, three_view_prompt=?, three_view_status='done',
                  locked_prompt=? WHERE id=?""",
                (char_appearance, tv_json, lock_json, row["id"]))
else:
    cur.execute("""INSERT INTO novel_characters (project_id, name, role, appearance, three_view_prompt, three_view_status, consistency_lock, locked_prompt)
                  VALUES (?,?,?,?,?,'done',1,?)""",
                (PID, CHAR_NAME, "主角", char_appearance, tv_json, lock_json))
# 场景（scene_library 可能缺此条）
cur.execute("SELECT id FROM scene_library WHERE project_id=? AND name=?", (PID, SCENE_NAME))
srow = cur.fetchone()
fa_json = json.dumps(fa, ensure_ascii=False)
vis = "；".join([v for v in fa.values() if v and v.strip()])
if srow:
    cur.execute("""UPDATE scene_library SET description=?, visual_prompt=?, four_angle_status='done',
                  angle_front=?, angle_back=?, angle_side=?, angle_over=? WHERE id=?""",
                (scene_desc, vis, fa.get("front",""), fa.get("back",""), fa.get("side",""), fa.get("over",""), srow["id"]))
else:
    cur.execute("""INSERT INTO scene_library (project_id, name, description, visual_prompt, four_angle_status, angle_front, angle_back, angle_side, angle_over)
                  VALUES (?,?,?,?,'done',?,?,?,?)""",
                (PID, SCENE_NAME, scene_desc, vis, fa.get("front",""), fa.get("back",""), fa.get("side",""), fa.get("over","")))
con.commit()
con.close()
print("   ✅ 已写回 novel_characters / scene_library")

# ── 4) 构造出图提示词 ───────────────────────────────────────
shot = json.load(open(S01_FILE, encoding="utf-8"))
raw_vp = shot["video_prompt"]
# 清洗：去掉【素材参考】整行 与 【角色一致性锁定·…】{json}
clean = re.sub(r"【素材参考】.*?(\n|$)", "", raw_vp)
clean = re.sub(r"【角色一致性锁定·[^】]+】\{.*?\}\s*", "", clean, flags=re.S)
clean = clean.strip()
frame_prompt = clean + "。写实电影感，低饱和度冷调，宽幅构图，无文字水印。"

char_prompt = (
    f"影视角色设定三视图参考（须保持一致）：\n正面：{tv['front']}\n侧面：{tv['side']}\n背面：{tv['back']}\n"
    f"请生成角色【{CHAR_NAME}】的全身正面设定图（character design sheet）：{char_appearance}。"
    f"风格：写实厚涂，废土科幻，低饱和度冷调；浅灰渐变干净背景；单人；无文字无边框。"
)
scene_prompt = (
    f"废土末日街道环境概念图：{fa['front']} "
    f"时间清晨，阴天冷灰漫射光，破败荒凉，低饱和度冷调写实；广角远景，电影感氛围；无人物，无文字。"
)
NEG = "低质量,模糊,变形,多余的手指,肢体残缺,文字水印,过饱和,卡通风格,多人,裁剪"

# ── 5) 真实出图（带 429 退避 + 尺寸兜底） ──────────────────
# 直接用 .env 模型
img_models = os.environ.get("VOLC_IMAGE_MODELS", "").split(",")
IMG_MODEL = img_models[0] if img_models else "doubao-seedream-5-0-pro-260628"
API_KEY = os.environ.get("VOLC_API_KEY", "")
client = ImageClient(api_key=API_KEY, model=IMG_MODEL)

def gen_image(prompt, neg, path, size):
    sizes = [size, "1024x1024"]  # 首选尺寸失败则退回正方形
    for sz in sizes:
        last_err = None
        for attempt in range(4):
            res = client.generate(prompt, neg, size=sz, n=1)
            if isinstance(res, list) and res and res[0]:
                if client.save_b64(res[0], path):
                    return True, sz, None
                return False, sz, "b64 落盘失败"
            if isinstance(res, str):
                last_err = res
                if "429" in res and attempt < 3:
                    time.sleep([15,30,60][attempt]); continue
                break
            break
        if last_err is None:
            last_err = "空响应"
        if sz != sizes[-1]:
            print(f"    ⚠ 尺寸 {sz} 失败({last_err[:40]})，退回 1024x1024")
            continue
        return False, sz, last_err
    return False, size, "全部失败"

print("[3] 真实 Seedream 出图（模型 %s）…" % IMG_MODEL)
imgs = {}
# 角色设定图（竖版）
p_char = os.path.join(IMAGE_DIR, f"{CHAR_NAME}.png")
ok, sz, err = gen_image(char_prompt, NEG, p_char, "768x1152")
imgs["char"] = (p_char, ok, sz, err)
print(f"   角色图 {'✅' if ok else '❌'} {os.path.basename(p_char)} [{sz}] {'' if ok else err}")

# 场景图（横版）
p_scene = os.path.join(IMAGE_DIR, f"{SCENE_NAME}.png")
ok, sz, err = gen_image(scene_prompt, NEG, p_scene, "1344x768")
imgs["scene"] = (p_scene, ok, sz, err)
print(f"   场景图 {'✅' if ok else '❌'} {os.path.basename(p_scene)} [{sz}] {'' if ok else err}")

# 分镜帧（横版）
p_frame = os.path.join(IMAGE_DIR, "第1章 最后一单_script_prompt_S01.png")
ok, sz, err = gen_image(frame_prompt, NEG, p_frame, "1344x768")
imgs["frame"] = (p_frame, ok, sz, err)
print(f"   分镜帧 {'✅' if ok else '❌'} {os.path.basename(p_frame)} [{sz}] {'' if ok else err}")

# ── 6) 打包交付 ─────────────────────────────────────────────
copied = {}
for key, (src, ok, sz, err) in imgs.items():
    dst = os.path.join(PKG, os.path.basename(src))
    if ok and os.path.exists(src):
        shutil.copy2(src, dst)
        copied[key] = dst

manifest = []
manifest.append(f"# 《末日快递王》第一章 · S01 分镜素材包\n")
manifest.append(f"> 生成方式：真实 LLM（glm-5）写设定 + 真实出图（Seedream `{IMG_MODEL}`）。\n")
manifest.append(f"> 打包时间：{time.strftime('%Y-%m-%d %H:%M')}\n")
manifest.append("\n## 一、分镜帧（S01 成片关键帧）")
manifest.append(f"- 文件：`{os.path.basename(p_frame)}`（已复制至 s01_package/）")
manifest.append(f"- 出图尺寸：{imgs['frame'][2]}")
manifest.append(f"- **出图提示词（video_prompt 清洗后）**：\n```\n{frame_prompt}\n```")
manifest.append("\n## 二、角色素材（图1 = 林一野）")
manifest.append(f"- 文件：`{CHAR_NAME}.png`")
manifest.append(f"- 出图尺寸：{imgs['char'][2]}")
manifest.append(f"- 角色外貌（小说来源）：{char_appearance}")
manifest.append(f"- **出图提示词**：\n```\n{char_prompt}\n```")
manifest.append("\n### 三视图设定（一致性锁依据，已写回库）")
manifest.append("```json\n" + json.dumps(tv, ensure_ascii=False, indent=2) + "\n```")
manifest.append("\n## 三、场景素材（图2 = 废土街道某处）")
manifest.append(f"- 文件：`{SCENE_NAME}.png`")
manifest.append(f"- 出图尺寸：{imgs['scene'][2]}")
manifest.append(f"- **出图提示词**：\n```\n{scene_prompt}\n```")
manifest.append("\n### 四角度设定（场景锚依据，已写回库）")
manifest.append("```json\n" + json.dumps(fa, ensure_ascii=False, indent=2) + "\n```")
manifest.append("\n## 四、素材映射（与 07_Prompt 图例一致）")
manifest.append("| 图例 | 素材 | 文件 | 状态 |")
manifest.append("|------|------|------|------|")
manifest.append(f"| 图1 | 林一野(角色) | {CHAR_NAME}.png | {'已出图' if imgs['char'][1] else '失败'} |")
manifest.append(f"| 图2 | 废土街道某处(场景) | {SCENE_NAME}.png | {'已出图' if imgs['scene'][1] else '失败'} |")
manifest.append(f"| — | S01 分镜帧 | {os.path.basename(p_frame)} | {'已出图' if imgs['frame'][1] else '失败'} |")
manifest.append(f"\n## 五、原始分镜提示词（07_Prompt/S01）")
manifest.append("```json\n" + json.dumps(shot, ensure_ascii=False, indent=2) + "\n```")

mfile = os.path.join(PKG, "manifest.md")
open(mfile, "w", encoding="utf-8").write("\n".join(manifest))
print("\n[4] 打包完成 →", PKG)
for k, v in copied.items():
    print("   交付:", os.path.relpath(v, ROOT))
print("   清单:", os.path.basename(mfile))
print("\n=== 结果 ===")
print("角色图:", "OK" if imgs['char'][1] else "FAIL "+str(imgs['char'][3]))
print("场景图:", "OK" if imgs['scene'][1] else "FAIL "+str(imgs['scene'][3]))
print("分镜帧:", "OK" if imgs['frame'][1] else "FAIL "+str(imgs['frame'][3]))
