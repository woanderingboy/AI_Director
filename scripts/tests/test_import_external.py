"""端到端实测：导入外部文件作为「素材」与「分镜提示词最终版」。

不启动真实服务、不调大模型——用 Flask 测试客户端直接打 /api/import/<pid>/import-external。
靶项目：末日快递王 (project_id=21)。
"""
import os
import sys
import json
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["AI_DIRECTOR_OFFLINE"] = "1"

from web import create_app
from web.models.database import db
from web.models.asset_models import AssetVersion

PROJECT_ID = 21
APP = create_app()
CLI = APP.test_client()

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def make_external_png(src, dst_name):
    """把项目内已有 PNG 复制到临时目录，模拟一份「外部」图片文件。"""
    tmp = tempfile.gettempdir()
    dst = os.path.join(tmp, dst_name)
    shutil.copy2(src, dst)
    return dst


def make_external_prompt(dst_name):
    """造一份外部分镜提示词 JSON（模拟从别处导出的镜头）。"""
    tmp = tempfile.gettempdir()
    dst = os.path.join(tmp, dst_name)
    data = {
        "shot_id": 99,
        "scene_id": "S99",
        "video_prompt": "【素材参考】外景·废土公路\n全景：黄昏的废弃高速公路，龟裂的沥青路面，远处坍塌的立交桥，"
                        "主角林一野推着改装快递车从画面右侧入镜，风卷起沙尘。",
        "negative_prompt": "卡通，低分辨率，畸变",
        "camera": "全景",
        "lighting": "黄昏逆光",
        "mood": "苍凉",
        "duration": "5s",
        "characters": ["林一野"],
    }
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return dst


with APP.app_context():
    # 预清理：清除历史崩溃遗留的测试产物，避免污染判定
    from web.models.asset_models import AssetVersion as _AV
    _AV.query.filter_by(project_id=PROJECT_ID, asset_type="reference", asset_key="外景_废土公路").delete()
    for k in ("外部分镜_S99", "外部分镜_S98"):
        _AV.query.filter_by(project_id=PROJECT_ID, asset_type="storyboard_prompt", asset_key=k).delete()
    db.session.commit()
    _root = os.path.join(APP.config["ROOT_PATH"], "02_Projects", "末日快递王")
    for d, pref in [("08_Image", "外景_废土公路"), ("07_Prompt", "外部分镜_S9")]:
        dd = os.path.join(_root, d)
        if os.path.isdir(dd):
            for fn in os.listdir(dd):
                if fn.startswith(pref):
                    try:
                        os.remove(os.path.join(dd, fn))
                    except Exception:
                        pass

    # ---------- 测试 A：外部图片 → 素材（最终版） ----------
    src_png = os.path.join(
        APP.config["ROOT_PATH"], "02_Projects", "末日快递王",
        "08_Image", "characters", "林一野", "v2.png"
    )
    ext_png = make_external_png(src_png, "external_ref_废土公路.png")
    with open(ext_png, "rb") as f:
        r = CLI.post(
            f"/api/import/{PROJECT_ID}/import-external",
            data={
                "file": (f, "external_ref_废土公路.png", "image/png"),
                "kind": "asset",
                "asset_key": "外景_废土公路",
                "as_final": "true",
                "notes": "实测：外部参考图导入为最终版素材",
            },
            content_type="multipart/form-data",
        )
    j = r.get_json()
    print("A 响应:", j)
    check("A1 素材导入接口返回 ok", j.get("ok") is True, str(r.status_code))
    check("A2 标记为最终版", j.get("is_final") is True)

    landed = j.get("path")
    check("A3 文件落盘 08_Image", bool(landed) and os.path.exists(landed), landed or "")

    row = AssetVersion.query.filter_by(
        project_id=PROJECT_ID, asset_type="reference", asset_key="外景_废土公路", is_final=True
    ).first()
    check("A4 asset_versions 登记且 is_final=1", row is not None,
          (row.content if row else "无记录"))

    # 幂等：同内容再导入一次（as_final=true），不应新建重复版本
    cnt_before = AssetVersion.query.filter_by(
        project_id=PROJECT_ID, asset_type="reference", asset_key="外景_废土公路"
    ).count()
    with open(ext_png, "rb") as f:
        r2 = CLI.post(
            f"/api/import/{PROJECT_ID}/import-external",
            data={
                "file": (f, "external_ref_废土公路.png", "image/png"),
                "kind": "asset",
                "asset_key": "外景_废土公路",
                "as_final": "true",
            },
            content_type="multipart/form-data",
        )
    cnt_after = AssetVersion.query.filter_by(
        project_id=PROJECT_ID, asset_type="reference", asset_key="外景_废土公路"
    ).count()
    check("A5 内容相同重复导入不新建版本(幂等)", cnt_after == cnt_before,
          f"导入前={cnt_before} 导入后={cnt_after} reused={r2.get_json().get('reused')}")

    # ---------- 测试 B：外部提示词 JSON → 分镜提示词最终版 ----------
    ext_json = make_external_prompt("external_shot_S99.json")
    with open(ext_json, "rb") as f:
        r = CLI.post(
            f"/api/import/{PROJECT_ID}/import-external",
            data={
                "file": (f, "external_shot_S99.json", "application/json"),
                "kind": "prompt",
                "asset_key": "外部分镜_S99",
                "as_final": "true",
                "notes": "实测：外部分镜提示词导入为最终版",
            },
            content_type="multipart/form-data",
        )
    j = r.get_json()
    print("B 响应:", j)
    check("B1 提示词导入接口返回 ok", j.get("ok") is True, str(r.status_code))
    check("B2 标记为最终版", j.get("is_final") is True)

    landed = j.get("path")
    check("B3 文件落盘 07_Prompt", bool(landed) and os.path.exists(landed), landed or "")

    # 校验落盘内容可被分镜画布读取（07_Prompt JSON 合法）
    try:
        data = json.load(open(landed, encoding="utf-8"))
        readable = isinstance(data, dict) and bool(data.get("video_prompt"))
    except Exception:
        readable = False
    check("B4 落盘 JSON 可被分镜画布解析", readable)

    row = AssetVersion.query.filter_by(
        project_id=PROJECT_ID, asset_type="storyboard_prompt",
        asset_key="外部分镜_S99", is_final=True
    ).first()
    check("B5 asset_versions 登记(storyboard_prompt)且 is_final=1", row is not None)

    # 最终版互斥：再导入一个不同 key 的 prompt 并标 final，确认前者仍独立
    ext_json2 = make_external_prompt("external_shot_S98.json")
    with open(ext_json2, "rb") as f:
        CLI.post(
            f"/api/import/{PROJECT_ID}/import-external",
            data={
                "file": (f, "external_shot_S98.json", "application/json"),
                "kind": "prompt", "asset_key": "外部分镜_S98", "as_final": "true",
            },
            content_type="multipart/form-data",
        )
    fin = AssetVersion.query.filter_by(
        project_id=PROJECT_ID, asset_type="storyboard_prompt", is_final=True
    ).all()
    keys = {v.asset_key for v in fin}
    check("B6 不同镜头的最终版各自独立", keys == {"外部分镜_S99", "外部分镜_S98"}, str(keys))

    # ---------- 清理：撤掉本次测试产生的数据，避免污染项目 ----------
    AssetVersion.query.filter_by(
        project_id=PROJECT_ID, asset_type="reference", asset_key="外景_废土公路"
    ).delete()
    for k in ("外部分镜_S99", "外部分镜_S98"):
        AssetVersion.query.filter_by(
            project_id=PROJECT_ID, asset_type="storyboard_prompt", asset_key=k
        ).delete()
    db.session.commit()
    # 删落盘文件（按前缀通配，避免漏删改名/多版本残留）
    _root = os.path.join(APP.config["ROOT_PATH"], "02_Projects", "末日快递王")
    for d, pref in [("08_Image", "外景_废土公路"), ("07_Prompt", "外部分镜_S9")]:
        dd = os.path.join(_root, d)
        if os.path.isdir(dd):
            for fn in os.listdir(dd):
                if fn.startswith(pref):
                    try:
                        os.remove(os.path.join(dd, fn))
                    except Exception:
                        pass

print("\n================ 实测结论 ================")
print(f"PASS: {len(PASS)}  FAIL: {len(FAIL)}")
if FAIL:
    print("未通过:", FAIL)
    sys.exit(1)
print("全部通过 ✓")
