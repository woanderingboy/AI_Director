import json, time, urllib.request, sqlite3, os

ROOT = r"D:\AI_Director"
DB = os.path.join(ROOT, "04_Output", "ai_video_data.db")
BASE = "http://127.0.0.1:5000"

# 找到已有的离线演示项目及其一个章节
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
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode()), r.status

# 列出该项目章节
chaps, _ = api("GET", f"/api/novel/{pid}/novel-chapters")
items = chaps if isinstance(chaps, list) else chaps.get("items", [])
assert items, "项目没有小说章节"
cid = items[0]["id"]
print(f"章节: id={cid} title={items[0].get('title')}")

# 触发真实 novel2script（文本模型，非图片）
resp, st = api("POST", "/api/pipeline/run", {
    "stage": "pipeline.novel2script",
    "project_id": pid,
    "chapter_id": cid,
})
print(f"提交任务: status={st} task_id={resp.get('task_id')}")

tid = resp["task_id"]
for _ in range(60):
    t, _ = api("GET", f"/api/tasks/{tid}")
    print(f"  · {t['status']} {t['progress']}% {t.get('message')}")
    if t["status"] in ("completed", "failed", "cancelled"):
        break
    time.sleep(3)

res = t.get("result") or {}
print("结果:", json.dumps(res, ensure_ascii=False)[:300])
if t["status"] == "completed":
    print("✅ 真实模型（火山引擎 glm-5-2-260617）一代小说→剧本 跑通成功")
else:
    print("❌ 任务未完成，请查看服务端日志 04_Output/server.log")
