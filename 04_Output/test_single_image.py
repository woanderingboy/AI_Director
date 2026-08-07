import os, dotenv, sys
sys.path.insert(0, r"D:\AI_Director")
dotenv.load_dotenv()
from web.services.image_client import ImageClient

key = os.environ.get("VOLC_API_KEY", "")
text_models = [m.strip() for m in os.environ.get("VOLC_TEXT_MODELS","").split(",") if m.strip()]
image_models = [m.strip() for m in os.environ.get("VOLC_IMAGE_MODELS","").split(",") if m.strip()]
print("key present:", bool(key), "| text:", text_models, "| image:", image_models)

model = image_models[0] if image_models else None
print("使用图片模型:", model)
client = ImageClient(api_key=key, model=model)
prompt = "电影级画面，暗调风格，深夜停车场，一名穿保安制服的男子手持手电筒巡逻，侧逆光，电影感构图，冷色调，高细节"
gen = client.generate(prompt, negative_prompt="低质量, 模糊, 卡通风格", size="1024x1024", n=1)
print("返回类型:", type(gen))
if isinstance(gen, list) and gen and gen[0]:
    out = r"D:\AI_Director\04_Output\seedream_test.png"
    ok = client.save_b64(gen[0], out)
    print("保存成功:", ok, "| 文件:", out, "| b64长度:", len(gen[0]))
else:
    print("结果:", gen)
