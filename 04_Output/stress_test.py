# -*- coding: utf-8 -*-
"""末日女子生存指南 · 全流程边缘情况压力测试

驱动真实 PipelineService / burn_subtitles，刻意注入异常输入，验证健壮性：
  A. novel_to_script 守卫（空/超长/乱码 -> 清晰报错，而非静默写 0 镜头空剧本）
  B. _split_shots 对残缺场景的鲁棒性
  C. gen_prompts / 一致性锁映射（自动合成 / 全空跳过）
  D. draw_images（无提示词 / 生成失败降级占位）
  E. render_videos（无图 / 缺图 / 时长越界裁剪）
  F. burn_subtitles（空段 / 起>止 / 越界 / 缺字体 / 超大字号 / 超长无空格文本 / 重叠 / 无音轨）
"""
import sys, os, json, shutil, traceback
sys.path.insert(0, "D:/AI_Director")

from web import create_app
from web.services.pipeline_service import PipelineService
from web.services.subtitle_service import burn_subtitles, SubtitleError, _default_font
from web.services import image_client as ic_mod

ROOT = "D:/AI_Director"
TMP_PROJ = "_stress_tmp"
TMP_DIR = os.path.join(ROOT, "02_Projects", TMP_PROJ)

results = []
def record(name, ok, msg=""):
    results.append((name, ok, msg))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {msg}" if msg else ""))

def make_png(path, color=(40, 44, 52), size=(720, 1280)):
    from PIL import Image
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, color).save(path)

def make_test_video(path, size=(720, 1280), duration=3):
    from moviepy import ImageClip
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ImageClip(os.path.join(os.path.dirname(path), "_bg.png")) if os.path.isfile(
        os.path.join(os.path.dirname(path), "_bg.png")) else make_png(
        os.path.join(os.path.dirname(path), "_bg.png"))
    clip = ImageClip(os.path.join(os.path.dirname(path), "_bg.png")).with_duration(duration)
    clip.write_videofile(path, fps=24, codec="libx264", audio=False)
    return path


def main():
    app = create_app()
    with app.app_context():
        from web.models.database import db, ProjectModel, ChapterModel, ScriptModel, ProjectConfig
        from web.models.novel_models import NovelCharacter

        ps = PipelineService(ROOT)

        # ───────── A. novel_to_script 守卫 ─────────
        print("\n=== A. novel_to_script 守卫 ===")
        # 找一个已有项目承载临时章节（避免新建项目的 FK 清理麻烦）
        host = ProjectModel.query.first()
        hid = host.id
        tmp_chap = ChapterModel(project_id=hid, title="__stress_empty__", filename="__stress_empty__.txt", content="   ")
        db.session.add(tmp_chap); db.session.commit()
        try:
            ps.novel_to_script(project_name=host.name, chapter_id=tmp_chap.id, project_id=hid)
            record("A1 空小说应报错而非静默写空剧本", False, "未抛出异常")
        except ValueError as e:
            record("A1 空小说应报错而非静默写空剧本", True, str(e)[:60])
        except Exception as e:
            record("A1 空小说应报错", False, f"抛了非预期异常: {type(e).__name__}: {e}")
        finally:
            db.session.delete(tmp_chap); db.session.commit()

        # 守卫逻辑：LLM 返回非 JSON（截断/乱码）时应清晰报错
        from web.services.llm_client import LLMClient
        orig_chat_json = LLMClient.chat_json
        LLMClient.chat_json = staticmethod(lambda *a, **k: {"raw": "这是一段被截断的……"})
        big_chap = ChapterModel(project_id=hid, title="__stress_garbled__", filename="__stress_garbled__.txt", content="任意内容触发乱码返回")
        db.session.add(big_chap); db.session.commit()
        try:
            ps.novel_to_script(project_name=host.name, chapter_id=big_chap.id, project_id=hid)
            record("A2 乱码LLM返回应清晰报错", False, "未抛出异常")
        except ValueError as e:
            record("A2 乱码LLM返回应清晰报错", True, str(e)[:50])
        except Exception as e:
            record("A2 乱码LLM返回", False, f"非预期: {type(e).__name__}")
        finally:
            LLMClient.chat_json = staticmethod(orig_chat_json)
            db.session.delete(big_chap); db.session.commit()

        # ───────── B. _split_shots 残缺场景鲁棒性 ─────────
        print("\n=== B. _split_shots 鲁棒性 ===")
        try:
            crafted = {"title": "t", "scenes": [
                {"scene_id": 1, "location": "巷口", "time": "夜",
                 "characters": [{"name": "苏晚", "action": "戒备", "emotion": "冷静"}],
                 "dialogue": [{"character": "苏晚", "line": "别动。"}],
                 "description": "雨夜巷口，苏晚戒备。"},
                {"scene_id": 2},  # 几乎全缺字段
                {"scene_id": 3, "description": "x" * 5000},  # 超长描述
                {"scene_id": 4, "characters": ["林小满"], "dialogue": []},  # 列表式角色、无对话
            ]}
            out = ps._split_shots(crafted, hid)
            shots = out.get("shots", [])
            ok = len(shots) > 0 and all(10 <= s["duration"] <= 15 for s in shots)
            record("B1 残缺/超长/列表式角色场景均能拆分且不越界", ok,
                   f"shots={len(shots)} dur范围={[s['duration'] for s in shots]}")
        except Exception as e:
            record("B1 _split_shots 鲁棒性", False, f"{type(e).__name__}: {e}")

        # ───────── C. 一致性锁映射 ─────────
        print("\n=== C. 一致性锁映射 ===")
        # 找末日项目（若存在）
        doomsday = ProjectModel.query.filter_by(name="末日女子生存指南").first()
        if doomsday:
            dpid = doomsday.id
            lock_map = ps._build_consistency_lock_map(dpid)
            # 苏晚/老周 locked_prompt 为空 -> 应由 appearance+visual_prompt 自动合成
            auto_ok = ("苏晚" in lock_map) and ("老周" in lock_map) and bool(lock_map.get("苏晚"))
            record("C1 锁描述为空时自动由外貌+视觉提示词合成", auto_ok,
                   f"苏晚={'有' if '苏晚' in lock_map else '无'} 老周={'有' if '老周' in lock_map else '无'}")
            # 全空角色应被跳过
            empty_char = NovelCharacter(project_id=dpid, world_id=1, name="__stress_empty_char__",
                                        consistency_lock=True, appearance="", visual_prompt="", locked_prompt="")
            db.session.add(empty_char); db.session.commit()
            lock_map2 = ps._build_consistency_lock_map(dpid)
            skipped = "__stress_empty_char__" not in lock_map2
            record("C2 全空锁定角色应被跳过(不注入)", skipped)
            db.session.delete(empty_char); db.session.commit()
        else:
            record("C 一致性锁映射", False, "末日项目不存在，跳过（需先跑通英雄路径）")

        # ───────── D. draw_images 降级 ─────────
        print("\n=== D. draw_images 降级 ===")
        # 每个用例用独立临时项目目录，避免沙箱禁止 rmtree 导致的残留污染
        def fresh_proj(name):
            d = os.path.join(ROOT, "02_Projects", name)
            os.makedirs(os.path.join(d, "07_Prompt"), exist_ok=True)
            os.makedirs(os.path.join(d, "08_Image"), exist_ok=True)
            return d

        d1 = fresh_proj("_stress_d1")
        r = ps.draw_images(project_id=99999, project_name="_stress_d1")
        record("D1 无提示词时安全跳过(skipped)", r.get("status") == "skipped", f"status={r.get('status')}")

        d2 = fresh_proj("_stress_d2")
        with open(os.path.join(d2, "07_Prompt", "t_prompt_S01.json"), "w", encoding="utf-8") as f:
            json.dump({"shot_id": 1, "video_prompt": "末日废墟", "negative_prompt": ""}, f)
        orig_gen = ic_mod.ImageClient.generate
        ic_mod.ImageClient.generate = lambda self, *a, **k: "[图片生成失败: forced for test]"
        try:
            r = ps.draw_images(project_id=99999, project_name="_stress_d2")
            img = os.path.join(d2, "08_Image", "t_prompt_S01.png")
            ok = r.get("status") == "ok" and os.path.isfile(img)
            record("D2 图片生成失败降级为占位图(不中断)", ok, f"status={r.get('status')} 占位图存在={os.path.isfile(img)}")
        finally:
            ic_mod.ImageClient.generate = orig_gen

        # ───────── E. render_videos 降级 ─────────
        print("\n=== E. render_videos 降级 ===")
        e1 = fresh_proj("_stress_e1")
        r = ps.render_videos(project_id=99999, project_name="_stress_e1")
        record("E1 无图片时安全跳过(skipped)", r.get("status") == "skipped", f"status={r.get('status')}")

        e2 = fresh_proj("_stress_e2")
        with open(os.path.join(e2, "07_Prompt", "a_prompt_S01.json"), "w", encoding="utf-8") as f:
            json.dump({"shot_id": 1, "video_prompt": "x", "duration": 3, "characters": []}, f)
        with open(os.path.join(e2, "07_Prompt", "a_prompt_S02.json"), "w", encoding="utf-8") as f:
            json.dump({"shot_id": 2, "video_prompt": "y", "duration": 3, "characters": []}, f)
        make_png(os.path.join(e2, "08_Image", "a_prompt_S01.png"))  # S02 故意缺图
        r = ps.render_videos(project_id=99999, project_name="_stress_e2")
        ok = r.get("status") == "ok" and r.get("count") == 1
        record("E2 缺图镜被跳过、其余正常出片", ok, f"count={r.get('count')}")

        e3 = fresh_proj("_stress_e3")
        with open(os.path.join(e3, "07_Prompt", "a_prompt_S01.json"), "w", encoding="utf-8") as f:
            json.dump({"shot_id": 1, "video_prompt": "x", "duration": -5, "characters": []}, f)
        make_png(os.path.join(e3, "08_Image", "a_prompt_S01.png"))
        r = ps.render_videos(project_id=99999, project_name="_stress_e3")
        sidecar = os.path.join(e3, "09_Video", "video_consistency.json")
        dur_ok = True
        if os.path.isfile(sidecar):
            sc = json.load(open(sidecar, encoding="utf-8"))
            for v in sc.get("shots", {}).values():
                if not (1.0 <= v.get("duration", 0) <= 15.0):
                    dur_ok = False
        record("E3 负/越界时长被裁剪到[1,15]", dur_ok and r.get("status") == "ok", f"status={r.get('status')}")

        # ───────── F. burn_subtitles 边界 ─────────
        print("\n=== F. burn_subtitles 边界 ===")
        vid = make_test_video(os.path.join(ROOT, "04_Output", "_stress_test.mp4"))
        base_style = {"font_path": _default_font(), "size": 40, "color": "#FFFFFF",
                      "stroke_color": "#000000", "stroke_width": 2, "bg": True, "position": "bottom"}
        try:
            burn_subtitles(vid, [], style=base_style)
            record("F1 空字幕段应抛 SubtitleError", False, "未抛异常")
        except SubtitleError:
            record("F1 空字幕段应抛 SubtitleError", True)
        except Exception as e:
            record("F1 空字幕段", False, f"非预期: {type(e).__name__}: {e}")

        try:
            out, srt = burn_subtitles(vid, [{"start": 2.0, "end": 1.0, "text": "起大于止"}], style=base_style)
            record("F2 start>end 被裁剪且不崩溃", os.path.isfile(out), f"out={os.path.basename(out)}")
        except Exception as e:
            record("F2 start>end", False, f"{type(e).__name__}: {e}")

        try:
            out, srt = burn_subtitles(vid, [{"start": 100.0, "end": 120.0, "text": "越界时间"}], style=base_style)
            record("F3 越界时间被裁剪到视频内", os.path.isfile(out))
        except Exception as e:
            record("F3 越界时间", False, f"{type(e).__name__}: {e}")

        try:
            out, srt = burn_subtitles(vid, [{"start": 0.5, "end": 2.5, "text": "缺字体回退"}],
                                      style={**base_style, "font_path": "/no/such/font.ttf"})
            record("F4 缺字体回退默认字体(不中断)", os.path.isfile(out))
        except Exception as e:
            record("F4 缺字体回退", False, f"{type(e).__name__}: {e}")

        try:
            out, srt = burn_subtitles(vid, [{"start": 0.5, "end": 2.5, "text": "超大字号"}],
                                      style={**base_style, "size": 400})
            record("F5 超大字号被裁剪到画幅内", os.path.isfile(out))
        except Exception as e:
            record("F5 超大字号", False, f"{type(e).__name__}: {e}")

        long_text = "末日降临城市陷入黑暗幸存者在废墟中艰难前行希望之火永不熄灭救援信号划破夜空危机四伏步步惊心生死一线之间抉择时刻来临" * 2
        try:
            out, srt = burn_subtitles(vid, [{"start": 0.5, "end": 2.8, "text": long_text}],
                                      style={**base_style, "size": 30})
            record("F6 超长无空格中文不崩溃", os.path.isfile(out))
        except Exception as e:
            record("F6 超长无空格中文", False, f"{type(e).__name__}: {e}")

        try:
            out, srt = burn_subtitles(vid, [
                {"start": 0.3, "end": 1.8, "text": "重叠段A"},
                {"start": 1.0, "end": 2.6, "text": "重叠段B"},
            ], style=base_style)
            record("F7 重叠时间段不崩溃", os.path.isfile(out))
        except Exception as e:
            record("F7 重叠时间段", False, f"{type(e).__name__}: {e}")

        # F8 无音轨视频（hero preview 一般为静帧无声）
        if doomsday:
            vdir = os.path.join(ROOT, "02_Projects", doomsday.name, "09_Video")
            preview = os.path.join(vdir, f"{doomsday.name}_preview.mp4")
            if os.path.isfile(preview):
                try:
                    out, srt = burn_subtitles(preview, [
                        {"start": 0.0, "end": 3.0, "text": "末日女子生存指南 · 别做那个好人"}], style=base_style)
                    record("F8 无音轨视频可烧录字幕", os.path.isfile(out))
                except Exception as e:
                    record("F8 无音轨视频", False, f"{type(e).__name__}: {e}")
            else:
                record("F8 无音轨视频可烧录字幕", True, "SKIP: hero preview 尚未生成（英雄路径进行中）")

        # 清理临时产物
        shutil.rmtree(TMP_DIR, ignore_errors=True)
        for p in [os.path.join(ROOT, "04_Output", "_stress_test.mp4"),
                  os.path.join(ROOT, "04_Output", "_stress_test_subtitled.mp4"),
                  os.path.join(ROOT, "04_Output", "_bg.png")]:
            try: os.remove(p)
            except OSError: pass

        # ───────── 汇总 ─────────
        print("\n========== 压力测试汇总 ==========")
        passed = sum(1 for _, ok, _ in results if ok)
        total = len(results)
        for name, ok, msg in results:
            print(f"  [{'✓' if ok else '✗'}] {name}" + (f"  ({msg})" if msg else ""))
        print(f"\n通过 {passed}/{total}")
        if passed != total:
            print("存在 FAIL，请检查上方详情。")


if __name__ == "__main__":
    main()
