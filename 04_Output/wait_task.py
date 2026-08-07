import json, time, urllib.request, os

BASE = "http://127.0.0.1:5000"
TID = "4cdf148631984bf6"
ROOT = r"D:\AI_Director"
PNAME = "离线演示项目"

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode())

last = ""
for i in range(90):  # 最多 ~15 分钟
    t = get(f"/api/tasks/{TID}")
    line = f"{t['status']:9s} {str(t['progress']):>3s}%  {t.get('message')}"
    if line != last:
        print(f"[{i*10}s] {line}", flush=True)
        last = line
    if t["status"] in ("success", "fail", "cancelled"):
        print(">>> 任务结束:", t["status"], flush=True)
        res = t.get("result") or {}
        print("RESULT:", json.dumps(res, ensure_ascii=False)[:600], flush=True)
        break
    time.sleep(10)

print("\n=== 最终产物 ===", flush=True)
for cat in ["05_Script", "07_Prompt", "08_Image", "09_Video"]:
    d = os.path.join(ROOT, "02_Projects", PNAME, cat)
    if os.path.isdir(d):
        fs = [f for f in os.listdir(d) if not f.startswith(".")]
        print(f"  {cat}: {len(fs)} 个", flush=True)
        for f in sorted(fs):
            fp = os.path.join(d, f)
            print(f"      {f}  ({os.path.getsize(fp)//1024} KB)", flush=True)
