import json, time, urllib.request, sqlite3, os

ROOT = r"D:\AI_Director"
DB = os.path.join(ROOT, "04_Output", "ai_video_data.db")
BASE = "http://127.0.0.1:5000"

conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute("SELECT id,name FROM projects WHERE name LIKE '%离线演示%' LIMIT 1")
row = cur.fetchone()
conn.close()
assert row, "未找到演示项目"
pid, pname = row
print(f"项目: id={pid} name={pname}")

def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode()), r.status

chaps, _ = api("GET", f"/api/novel/{pid}/novel-chapters")
items = chaps if isinstance(chaps, list) else chaps.get("items", [])
assert items, "项目没有小说章节"
cid = items[0]["id"]
print(f"章节: id={cid} title={items[0].get('title')}")

print("\n>>> 提交 run_all（四阶段全真实执行）")
resp, st = api("POST", "/api/pipeline/run", {
    "stage": "pipeline.run_all",
    "project_id": pid,
    "chapter_id": cid,
    "project_name": pname,
})
print(f"提交: status={st} task_id={resp.get('task_id')}")
tid = resp["task_id"]

for _ in range(120):
    t, _ = api("GET", f"/api/tasks/{tid}")
    print(f"  · {t['status']:9s} {str(t['progress']):>3s}%  {t.get('message')}")
    if t["status"] in ("success", "fail", "cancelled"):
        break
    time.sleep(4)

res = t.get("result") or {}
print("\n=== 最终结果 ===")
print(json.dumps(res, ensure_ascii=False, indent=2)[:1200])

# 校验产出文件
print("\n=== 产出文件 ===")
for cat in ["05_Script", "07_Prompt", "08_Image", "09_Video"]:
    d = os.path.join(ROOT, "02_Projects", pname, cat)
    if os.path.isdir(d):
        fs = [f for f in os.listdir(d) if not f.startswith(".")]
        print(f"  {cat}: {len(fs)} 个 -> {fs[:8]}")
