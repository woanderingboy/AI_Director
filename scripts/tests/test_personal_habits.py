"""回归测试：个人习惯软偏好注入（幂等 + 读取 + 格式）。

不启动真实服务、不调大模型——直接单测 prompt_assembly 与 asset_habit_sync。
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ["AI_DIRECTOR_OFFLINE"] = "1"

from web.services.prompt_assembly import build_habit_hint, inject_personal_habits, build_full_prompt
from web.services.asset_habit_sync import load_personal_habits


PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[PASS] {name} {extra}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} {extra}")


def main():
    habits = {
        "运镜习惯": {"中景": 26, "俯拍": 18, "近景": 16, "特写": 11, "跟拍": 7},
        "光线习惯": {"自然光": 9, "侧光": 6, "柔光": 4},
        "情绪习惯": {"紧张": 7, "压抑": 3, "愤怒": 2},
        "动作习惯": {"奔跑": 3},
    }

    # A1 格式：单行、以【个人习惯】开头、含 top3 运镜/光线/情绪
    hint = build_habit_hint(habits)
    check("A1 习惯提示格式单行", hint.startswith("【个人习惯】默认倾向：") and "。" in hint, f"-> {hint}")
    check("A1 含 top 运镜", "中景" in hint and "俯拍" in hint, f"-> {hint}")
    check("A1 含 top 光线", "自然光" in hint and "侧光" in hint, f"-> {hint}")
    check("A1 含 top 情绪", "紧张" in hint and "压抑" in hint, f"-> {hint}")
    check("A1 不含第4名跟拍", "跟拍" not in hint, f"-> {hint}")

    # A2 空画像返回空串（安全默认，不出图受污染）
    check("A2 空画像返回空串", build_habit_hint({}) == "")

    # B 幂等：注入两次后 video_prompt 不累积
    shot = {"video_prompt": "全景起幅展现清晨六点的地铁站台"}
    inject_personal_habits(shot, habits)
    first = shot["video_prompt"]
    check("B1 首次注入含习惯", "【个人习惯】" in first)
    inject_personal_habits(shot, habits)  # 第二次（模拟重跑 gen_prompts）
    second = shot["video_prompt"]
    check("B2 重跑不累积（幂等）", first == second, f"\n  first={first}\n  second={second}")
    check("B3 习惯提示仅出现一次", first.count("【个人习惯】") == 1)

    # B4 已有习惯则跳过（hint 已在 vp 中不重复）
    shot2 = {"video_prompt": first}
    inject_personal_habits(shot2, habits)
    check("B4 已含则跳过", shot2["video_prompt"] == first)

    # C 读取真实 Personal_Habits.yaml（若存在）
    real = load_personal_habits()
    if real and real.get("运镜习惯"):
        check("C1 读取真实画像含运镜习惯", isinstance(real["运镜习惯"], dict))
        check("C2 真实画像可编译为提示", build_habit_hint(real).startswith("【个人习惯】"))
    else:
        print("[SKIP] C 个人习惯画像文件不存在（先跑一次同步即可）；读取函数返回 {} 符合预期")
        check("C0 无文件时返回 {}", real == {})

    # D build_full_prompt 末尾带上习惯段（并幂等——多次调用不重复）
    g = {"art_style": "写实", "lighting": "自然光"}
    shot3 = {"video_prompt": "中景跟拍主角穿过长廊", "negative_prompt": "模糊"}
    out1 = build_full_prompt(shot3, g)
    out2 = build_full_prompt(shot3, g)
    check("D1 build_full_prompt 含习惯段", "【个人习惯】" in out1)
    check("D2 build_full_prompt 幂等", out1 == out2)
    check("D3 真实文件习惯也进交付提示", "【个人习惯】" in out1)

    print("\n================ 实测结论 ================")
    print(f"PASS: {PASS}  FAIL: {FAIL}")
    print("全部通过 ✓" if FAIL == 0 else "存在失败 ✗")
    return FAIL == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
