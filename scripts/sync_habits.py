# -*- coding: utf-8 -*-
"""一键把最终资产 / 项目习惯同步整理进全局资产库（01_Global_Assets）。

离线可用（默认纯规则提取，不调大模型）。用法：
  python scripts/sync_habits.py                 # 扫描所有项目最终资产
  python scripts/sync_habits.py --project-id 21 # 只扫末日快递王
  python scripts/sync_habits.py --dry-run       # 只打印将要新增的清单，不落盘
  python scripts/sync_habits.py --use-llm       # 调用大模型补描述/提示词（需已配 Key）

逻辑：提取最终分镜里的运镜/光线/情绪/动作习惯 + 项目全局设定，
增量合并进全局资产库（同名跳过、负面偏好合并去重）。
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web import create_app
from web.services.asset_habit_sync import sync_final_assets_to_globals


def main():
    ap = argparse.ArgumentParser(description="一键同步最终资产习惯到全局资产库")
    ap.add_argument("--project-id", type=int, default=None, help="只扫指定项目（默认全部）")
    ap.add_argument("--use-llm", action="store_true", help="调用大模型补描述/提示词")
    ap.add_argument("--dry-run", action="store_true", help="只打印清单，不落盘")
    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        report = sync_final_assets_to_globals(
            project_id=args.project_id, use_llm=args.use_llm, dry_run=args.dry_run)

    print(f"\n扫描最终分镜数: {report['scanned_shots']}  | project_id: {report['project_id']}")
    print(f"\n=== 将新增 / 已新增 ({len(report['added'])}) ===")
    for a in report["added"]:
        print("  +", a)
    print(f"\n=== 已跳过(库中同名存在, {len(report['skipped'])}) ===")
    for s in report["skipped"]:
        print("  =", s)
    print(f"\n=== negative_prompts.yaml 更新字段: {report['negative_updated'] or '无'} ===")
    if args.dry_run:
        print("\n[dry-run] 未落盘，去掉 --dry-run 后执行真实写入。")


if __name__ == "__main__":
    main()
