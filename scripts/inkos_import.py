#!/usr/bin/env python
"""CLI：把 inkos 书籍目录回写到 AI Director 创作库。

用法：
  python scripts/inkos_import.py --book-dir "C:/.../books/末日苏晚" --project-id 1
  python scripts/inkos_import.py --book-dir "..." --project-name "我的项目"
  python scripts/inkos_import.py --book-dir "..." --project-name "我的项目" --create-project

- 需先确保 AI Director 已存在目标项目（或用 --create-project 自动建）。
- book_dir 必须是 inkos `book create` 生成的书籍目录（内含 book.json 与 story/）。
"""
import os
import sys
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from web import create_app  # noqa: E402
from web.models.database import db, ProjectModel  # noqa: E402
from web.services.inkos_import import import_inkos_book  # noqa: E402


def resolve_project(args):
    if args.project_id:
        p = ProjectModel.query.get(args.project_id)
        if not p:
            raise SystemExit(f"项目 id={args.project_id} 不存在")
        return p
    if args.project_name:
        p = ProjectModel.query.filter_by(name=args.project_name).first()
        if p:
            return p
        if args.create_project:
            p = ProjectModel(name=args.project_name, genre="剧情")
            db.session.add(p)
            db.session.commit()
            print(f"[+] 已创建项目：{args.project_name} (id={p.id})")
            return p
        raise SystemExit(f"项目名「{args.project_name}」不存在，加 --create-project 可自动创建")
    raise SystemExit("请通过 --project-id 或 --project-name 指定目标项目")


def main():
    ap = argparse.ArgumentParser(description="inkos 书籍回写 AI Director")
    ap.add_argument("--book-dir", required=True, help="inkos 书籍目录（含 book.json 与 story/）")
    ap.add_argument("--project-id", type=int, help="目标项目 id")
    ap.add_argument("--project-name", help="目标项目名（不存在则报错，除非 --create-project）")
    ap.add_argument("--create-project", action="store_true", help="项目名不存在时自动创建")
    ap.add_argument("--source-tag", default="inkos", help="PlotPoint 来源标记（默认 inkos）")
    ap.add_argument("--no-appearance", action="store_true",
                    help="关闭 LLM 自动生成角色外貌/视觉提示词")
    ap.add_argument("--auto-lock", action="store_true",
                    help="导入后自动开启（导入的）主角一致性锁")
    args = ap.parse_args()

    book_dir = os.path.abspath(args.book_dir)
    if not os.path.isdir(book_dir):
        raise SystemExit(f"book_dir 不存在：{book_dir}")

    app = create_app()
    with app.app_context():
        project = resolve_project(args)
        print(f"[*] 目标项目：{project.name} (id={project.id})")
        print(f"[*] 书籍目录：{book_dir}")
        stat = import_inkos_book(
            project.id, book_dir,
            source_tag=args.source_tag,
            gen_appearance=not args.no_appearance,
            auto_lock_main=args.auto_lock,
        )
        print("[+] 回写完成：")
        for k, v in stat.items():
            print(f"    {k}: {v}")


if __name__ == "__main__":
    main()
