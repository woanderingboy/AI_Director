# -*- coding: utf-8 -*-
"""生成《末日快递王》主角 林一野 的多版形象（img2img 保脸）。

- 以现有 08_Image/林一野.png 为参考（登记为 v1），生成 v2/v3/v4 三版"更好看"变体。
- 全部写入 asset_versions(is_final=False) 与 08_Image/characters/林一野/vN.png，互不覆盖。
- 生成对比拼图 contact_sheet.png 便于可视化挑选。
- 不做最终版：等你确认后用 `--final vX` 把该版复制进最终素材库 08_Image/林一野.png 并标记 is_final。

用法：
  python scripts/gen_char_versions.py            # 生成多版 + 拼图
  python scripts/gen_char_versions.py --final v3 # 把 v3 设为最终版
"""
import os, sys, time, shutil, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dotenv
dotenv.load_dotenv()
os.environ["AI_DIRECTOR_OFFLINE"] = "0"

ROOT = os.path.abspath(".")
PID = 21
CHAR_NAME = "林一野"
IMG_DIR = os.path.join(ROOT, "02_Projects", "末日快递王", "08_Image")
CHAR_DIR = os.path.join(IMG_DIR, "characters", CHAR_NAME)
os.makedirs(CHAR_DIR, exist_ok=True)
CANON = os.path.join(IMG_DIR, f"{CHAR_NAME}.png")   # 最终素材库（canonical）

MODELS = os.environ.get("VOLC_IMAGE_MODELS", "").split(",")
IMG_MODEL = MODELS[0] if MODELS else "doubao-seedream-5-0-pro-260628"
API_KEY = os.environ.get("VOLC_API_KEY", "")
NEG = "低质量,模糊,变形,多余的手指,肢体残缺,文字水印,过饱和,卡通风格,多人,裁剪,美化滤镜"

# 三版方向（均保持 v1 身份：高眉骨/深眼窝/废土硬汉/旧夹克）
VARIANTS = {
    "v2": "保持同一人物身份（高眉骨、深眼窝、废土硬汉气质），优化为更立体英气的五官轮廓，眼神更锐利有神，"
          "面部光影更立体 flattering，身穿袖口短一截的旧夹克，电影级柔和侧光，写实厚涂，单人，浅灰背景，无文字无边框。",
    "v3": "保持同一人物身份（高眉骨、深眼窝、废土硬汉气质），改为更清爽利落的中年硬汉：刮净胡茬，利落短发，"
          "面容更俊朗干净，冷调天光，身穿袖口短一截的旧夹克，电影级干净打光，写实厚涂，单人，浅灰背景，无文字无边框。",
    "v4": "保持同一人物身份（高眉骨、深眼窝、废土硬汉气质），强化沧桑故事感：保留胡茬但面部更立体，"
          "深眼窝阴影更明显，戏剧性伦勃朗光刻画骨骼，风霜感更强，身穿袖口短一截的旧夹克，写实厚涂，单人，浅灰背景，无文字无边框。",
}


def gen_ref(client, ref_path, prompt, path, size="1024x1024"):
    sizes = [size, "1024x1024"]
    for sz in sizes:
        last_err = None
        for attempt in range(5):
            try:
                res = client.generate_with_ref([ref_path], prompt, NEG, size=sz, n=1)
            except Exception as e:
                last_err = str(e)[:160]; time.sleep(min(2 ** attempt * 5, 40)); continue
            if isinstance(res, list) and res and res[0]:
                if client.save_b64(res[0], path):
                    return True, sz, None
                last_err = "save_b64 失败"
            elif isinstance(res, str):
                last_err = res
                if "429" in res:
                    time.sleep(min(2 ** attempt * 5, 40)); continue
                # SSL / 网络抖动：退避重试
                time.sleep(min(2 ** attempt * 4 + 3, 30)); continue
            else:
                last_err = "空结果"; time.sleep(3)
        if last_err:
            # 换尺寸前先打印
            print(f"    ⚠ [{sz}] 重试耗尽: {last_err[:80]}")
    return False, size, last_err or "重试耗尽"


def register_version(session_maker, version_tag, rel_path, notes):
    from web.models.asset_models import AssetVersion
    av = AssetVersion.query.filter_by(project_id=PID, asset_type="character",
                                      asset_key=CHAR_NAME, version_tag=version_tag).first()
    if not av:
        av = AssetVersion(project_id=PID, asset_type="character", asset_key=CHAR_NAME,
                          version_tag=version_tag)
        session_maker.add(av)
    av.content = rel_path
    av.notes = notes
    av.is_final = False
    session_maker.commit()


def build_contact_sheet():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    files = [os.path.join(CHAR_DIR, f"{v}.png") for v in ["v1", "v2", "v3", "v4"]]
    if not all(os.path.exists(f) for f in files):
        return None
    imgs = [Image.open(f).convert("RGB") for f in files]
    w, h = imgs[0].size
    scale = 360 / w
    tw, th = int(w * scale), int(h * scale)
    LABEL_H = 28
    GAP = 15
    sheet = Image.new("RGB", (tw * 2 + 30, th * 2 + 2 * LABEL_H + 2 * GAP + 20), (20, 20, 22))
    d = ImageDraw.Draw(sheet)
    # 找中文能用的字体
    font = None
    for fp in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyh.ttf",
               r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc",
               "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
               "/System/Library/Fonts/PingFang.ttc"]:
        if os.path.exists(fp):
            try: font = ImageFont.truetype(fp, 22); break
            except Exception: pass
    if font is None:
        font = ImageFont.load_default()
    pos = [(10, 10), (tw + 20, 10), (10, th + LABEL_H + GAP + 10), (tw + 20, th + LABEL_H + GAP + 10)]
    labels = ["v1 (原版/参考)", "v2 硬朗英气", "v3 清爽俊朗", "v4 沧桑故事感"]
    for i, (p, img) in enumerate(zip(pos, imgs)):
        sheet.paste(img.resize((tw, th)), p)
        d.text((p[0], p[1] + th + 4), labels[i], fill=(235, 235, 235), font=font)
    out = os.path.join(CHAR_DIR, "contact_sheet.png")
    sheet.save(out)
    return out


def set_final(version_tag):
    from web.models.asset_models import AssetVersion
    src = os.path.join(CHAR_DIR, f"{version_tag}.png")
    if not os.path.exists(src):
        print(f"❌ 找不到 {src}"); return
    shutil.copy(src, CANON)
    for av in AssetVersion.query.filter_by(project_id=PID, asset_type="character", asset_key=CHAR_NAME):
        av.is_final = (av.version_tag == version_tag)
    db.session.commit()
    print(f"✅ 已将 {version_tag} 设为最终版 → {CANON}（is_final 标记已更新）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", help="把某版设为最终版，例如 v3")
    args = ap.parse_args()

    from web import create_app
    from web.models.database import db
    app = create_app()
    with app.app_context():
        if args.final:
            set_final(args.final)
            return

        client = ImageClient(api_key=API_KEY, model=IMG_MODEL)

        # v1 = 现有 canonical 图，登记并复制到版本目录
        if os.path.exists(CANON):
            shutil.copy(CANON, os.path.join(CHAR_DIR, "v1.png"))
            register_version(db.session, "v1",
                             f"08_Image/characters/{CHAR_NAME}/v1.png", "原始生成版（参考底图）")
            print("✅ v1 (原版) 已登记")
        else:
            print("⚠ 找不到 08_Image/林一野.png，无法登记 v1")

        # 生成 v2/v3/v4
        for tag, prompt in VARIANTS.items():
            out = os.path.join(CHAR_DIR, f"{tag}.png")
            print(f"[生成 {tag}] …")
            ok, sz, err = gen_ref(client, os.path.join(CHAR_DIR, "v1.png"), prompt, out)
            if ok:
                register_version(db.session, tag,
                                 f"08_Image/characters/{CHAR_NAME}/{tag}.png", prompt[:60])
                print(f"   ✅ {tag} 成功 [{sz}]")
            else:
                print(f"   ❌ {tag} 失败: {err}")

        sheet = build_contact_sheet()
        print("\n=== 结果 ===")
        from web.models.asset_models import AssetVersion
        for av in AssetVersion.query.filter_by(project_id=PID, asset_type="character", asset_key=CHAR_NAME):
            print(f"  {av.version_tag}: is_final={av.is_final}  path={av.content}")
        print(f"  对比拼图: {sheet}" if sheet else "  ⚠ 未生成拼图(PIL 不可用)")
        print("\n⏳ 尚未设定最终版。你确认后运行：python scripts/gen_char_versions.py --final vX")


if __name__ == "__main__":
    from web.services.image_client import ImageClient
    from web.models.database import db
    main()
