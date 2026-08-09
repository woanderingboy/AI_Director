"""打包功能现场验证：用 app.test_client() 跑三种场景。
每个场景用唯一项目名，避免在 Python 内做删除（沙箱安全删除会拦截 rmtree/remove）。
文件夹清理由调用方用 Bash 完成；此处只清 DB 行。
"""
import os, sys, json
sys.path.insert(0, r"D:\AI_Director")
from PIL import Image
from app import create_app
from web.models.database import db, ProjectModel

ROOT = r"D:\AI_Director"
BASE = "打包测试演示"
created = []  # (pid, name)

def make_png(path, color):
    Image.new("RGB", (4, 4), color).save(path)

def make_project(suffix):
    name = f"{BASE}_{suffix}"
    proj = ProjectModel(name=name, genre="测试", description="打包功能现场验证")
    db.session.add(proj); db.session.commit()
    pid = proj.id
    created.append((pid, name))
    return pid, name

def build(name, multi=True, empty=False, missing_ref=True):
    d = os.path.join(ROOT, "02_Projects", name)
    if not empty:
        img = os.path.join(d, "08_Image"); os.makedirs(img, exist_ok=True)
        make_png(os.path.join(img, "场景A.png"), (10, 20, 30))
        if multi:
            make_png(os.path.join(img, "苏晚_final.png"), (120, 0, 0))
            make_png(os.path.join(img, "苏晚_v2.png"), (0, 120, 0))
        pd = os.path.join(d, "07_Prompt"); os.makedirs(pd, exist_ok=True)
        if missing_ref:
            with open(os.path.join(pd, "demo_prompt_S01.json"), "w", encoding="utf-8") as f:
                json.dump({"shot_id": "S01", "characters": ["路人甲"],
                           "location": "废墟医院", "video_prompt": "测试"}, f, ensure_ascii=False)

app = create_app()
ctx = app.app_context(); ctx.push()
client = app.test_client()

print("===== 场景A：多版本 + 缺失参考图 =====")
pidA, nameA = make_project("A")
build(nameA, multi=True, empty=False, missing_ref=True)
r = client.post(f"/api/asset-packages/{pidA}/analyze", json={}); a = r.get_json()
print("analyze HTTP", r.status_code, "| total_files", a["total_files"],
      "| need_confirm", a["need_confirm_count"], "| missing_ref", a["missing_ref_count"],
      "| missing_count", a["missing_count"])
print("  need_confirm:", [x["asset_key"] for x in a["assets"] if x["status"] == "need_confirm"])
print("  missing_ref :", [x["asset_key"] for x in a["assets"] if x["status"] == "missing"])

r = client.post(f"/api/asset-packages/{pidA}/create", json={"name": "pkgA"}); cj = r.get_json()
print("create(无选择) HTTP", r.status_code, "status=", cj.get("status"), "pkg_id=", cj.get("id"))
pkg_id = cj["id"]
r = client.post(f"/api/asset-packages/packages/{pkg_id}/export", json={})
ej = r.get_json(silent=True)
print("export(无选择) HTTP", r.status_code, "raw=", (r.get_data(as_text=True)[:160] if ej is None else ej))
if ej:
    print("  ok=", ej.get("ok"), "blocked=", ej.get("blocked"), "->", ej.get("error"))

r = client.post(f"/api/asset-packages/{pidA}/create",
                json={"name": "pkgA2", "selection": {"filegroup:苏晚": "苏晚_final.png"}})
cj2 = r.get_json(); print("create(选最终版) HTTP", r.status_code, "status=", cj2.get("status"))
pkg_id2 = cj2["id"]
r = client.post(f"/api/asset-packages/packages/{pkg_id2}/export",
                json={"selection": {"filegroup:苏晚": "苏晚_final.png"}})
ej2 = r.get_json(silent=True)
print("export(选最终版) HTTP", r.status_code, "raw=", (r.get_data(as_text=True)[:160] if ej2 is None else ej2))
if ej2:
    print("  ok=", ej2.get("ok"), "exported_count=", ej2.get("exported_count"), "dir=", ej2.get("export_dir"))

print("\n===== 场景B：完全空素材（硬缺失）=====")
pidB, nameB = make_project("B")
build(nameB, multi=False, empty=True, missing_ref=False)
r = client.post(f"/api/asset-packages/{pidB}/analyze", json={}); ab = r.get_json()
print("analyze HTTP", r.status_code, "| total_files", ab["total_files"], "| missing_count", ab["missing_count"])
r = client.post(f"/api/asset-packages/{pidB}/create", json={"name": "pkgB"}); pb = r.get_json()
pkg_idB = pb["id"]
r = client.post(f"/api/asset-packages/packages/{pkg_idB}/export", json={}); eb = r.get_json(silent=True)
print("export(空) HTTP", r.status_code, "raw=", (r.get_data(as_text=True)[:160] if eb is None else eb))
if eb:
    print("  ok=", eb.get("ok"), "->", eb.get("error"))

print("\n===== 场景C：末日项目（正常单文件，pid=2）=====")
r = client.post("/api/asset-packages/2/analyze", json={}); ac = r.get_json()
print("analyze HTTP", r.status_code, "| total_files", ac["total_files"],
      "| need_confirm", ac["need_confirm_count"], "| missing_ref", ac["missing_ref_count"],
      "| missing_count", ac["missing_count"])

# 清 DB 行（不涉及文件删除）
for pid_, _ in created:
    p = ProjectModel.query.get(pid_)
    if p:
        db.session.delete(p)
db.session.commit()
print("\nDB 行已清理；文件夹 02_Projects/打包测试演示_* 待 Bash 删除")
