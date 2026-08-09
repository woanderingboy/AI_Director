"""剧本诊断路由：生成前体检 + 可选 AI 深度诊断。"""
import os
import json

from flask import Blueprint, jsonify, request, current_app
from web.models.database import db, ProjectModel
from web.models.novel_models import NovelCharacter
from web.services.script_doctor import analyze_scripts

bp = Blueprint("script_doctor", __name__, url_prefix="/api")


def _scan_script_files(root_path, project_name):
    proj_dir = os.path.join(root_path, "02_Projects", project_name)
    script_dir = os.path.join(proj_dir, "05_Script")
    scripts = []
    if not os.path.isdir(script_dir):
        return scripts
    for f in sorted(os.listdir(script_dir)):
        if not f.endswith(".json"):
            continue
        try:
            with open(os.path.join(script_dir, f), "r", encoding="utf-8") as fh:
                scripts.append(json.load(fh))
        except Exception:
            continue
    return scripts


@bp.route("/script-doctor/<int:project_id>", methods=["GET"])
def doctor_report(project_id):
    project = ProjectModel.query.get(project_id)
    if not project:
        return jsonify({"error": "项目不存在"}), 404
    root = current_app.config.get("ROOT_PATH") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    scripts = _scan_script_files(root, project.name)
    lib = [c.to_dict() for c in NovelCharacter.query.filter_by(project_id=project_id).all()]
    report = analyze_scripts(scripts, lib)
    report["project_id"] = project_id
    report["project_name"] = project.name
    return jsonify(report)


@bp.route("/script-doctor/<int:project_id>/ai-review", methods=["POST"])
def doctor_ai_review(project_id):
    """调用 LLM，以专业编剧视角给出深度评语（仅耗 token，不耗图片额度）。"""
    project = ProjectModel.query.get(project_id)
    if not project:
        return jsonify({"error": "项目不存在"}), 404
    root = current_app.config.get("ROOT_PATH") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    scripts = _scan_script_files(root, project.name)
    if not scripts:
        return jsonify({"error": "未找到剧本，请先生成剧本"}), 400

    # 先用确定性体检拿到要点，作为给 LLM 的上下文
    lib = [c.to_dict() for c in NovelCharacter.query.filter_by(project_id=project_id).all()]
    report = analyze_scripts(scripts, lib)
    issues_txt = "\n".join(
        f"- [{i['severity']}] {i['category'] if i.get('category') else ''}：{i['text']}"
        for i in report["issues"]
    )
    script_summary = "\n\n".join(
        f"【{sc.get('title', '剧本')}】\n" + "\n".join(
            f"场{s.get('scene_id')}｜{s.get('location','')}｜{s.get('mood','')}｜"
            f"角色：{','.join((c.get('name') if isinstance(c,dict) else c) for c in s.get('characters',[]))}\n"
            f"动作/{s.get('description','')[:120]}"
            for s in (sc.get("scenes") or [])
        )
        for sc in scripts[:3]
    )

    from web.services.novel_ai_service import _get_client_for_stage
    client, llm_cfg = _get_client_for_stage("doctor", project_id)
    system = (
        "你是一位从业 15 年的专业影视编剧与剧本医生（Script Doctor）。"
        "请用中文、分「结构 / 人物压力 / 节奏」三段给出犀利但可执行的诊断，"
        "每段的结论控制在 3-5 条，必须给出具体的修改方向（不要泛泛而谈），"
        "并在末尾用一句话总结这份剧本目前的「可拍性」。"
    )
    user = (
        f"项目：《{project.name}》\n\n"
        f"=== 剧本概要 ===\n{script_summary}\n\n"
        f"=== 自动体检已发现问题（供你参考/深挖）===\n{issues_txt}\n\n"
        "请基于以上，给出你的专业诊断与修改建议。"
    )
    try:
        resp = client.chat(messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ], temperature=llm_cfg.get("temperature", 0.7), max_tokens=llm_cfg.get("max_tokens", 2000))
        review = resp if isinstance(resp, str) else str(resp)
    except Exception as e:
        return jsonify({"error": f"AI 诊断失败：{e}"}), 502
    return jsonify({"review": review})


@bp.route("/script-doctor/<int:project_id>/reports", methods=["GET"])
def doctor_reports(project_id):
    """返回 gen_prompts 自动写入的每章体检报告（前端 Script Doctor 面板展示）。"""
    from web.models.novel_models import ScriptDoctorReport
    rows = ScriptDoctorReport.query.filter_by(project_id=project_id).order_by(
        ScriptDoctorReport.created_time.desc()
    ).all()
    out = []
    for r in rows:
        try:
            rep = json.loads(r.report_json) if r.report_json else {}
        except Exception:
            rep = {}
        out.append({
            "id": r.id,
            "chapter_key": r.chapter_key,
            "runtime_seconds": r.runtime_seconds,
            "created_time": str(r.created_time) if r.created_time else None,
            "overall_score": rep.get("overall_score"),
            "overall_grade": rep.get("overall_grade"),
            "issues": rep.get("issues", []),
            "categories": rep.get("categories", {}),
        })
    return jsonify({"project_id": project_id, "reports": out, "auto_run": True})
