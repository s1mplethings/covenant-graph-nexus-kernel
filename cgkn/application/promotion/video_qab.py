"""QAB video demonstration executed through the Host CapabilityTree/DAG.

The module deliberately uses Host capabilities and the public VeriArbor quality
policy. FFmpeg/Playwright/SAPI live here, never in ``src/veriarbor``.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from cgkn.execution import (
    BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError,
    ExecutionErrorCode, TaskContext,
)
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.orchestration.capability_tree import CapabilityNode, CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.orchestration.tree_edits import TreeEdit, apply_tree_edits

from veriarbor.quality import (
    CoverageStatus, QualityEvidence, QualityKind, QualityObligation,
    QualityPlan, QualityVerdict, changed_invalidation_keys,
)

APP_ROOT = Path(r"C:\Users\sunom\VeriArbor-Preview-Release\apps\promotion_studio")
PUBLIC_ROOT = Path(r"C:\Users\sunom\VeriArbor-Preview-Release")
FONT = Path(r"C:\Windows\Fonts\msyh.ttc")
FFMPEG = Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe")
FFPROBE = Path(r"C:\Program Files\ffmpeg\bin\ffprobe.exe")
PY = Path(sys.executable)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                               default=dict) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run(command: list[str], *, cwd: Path | None = None, timeout: int = 300,
        check: bool = True) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        command, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(
            "command failed (%s): %s\nSTDOUT:\n%s\nSTDERR:\n%s" % (
                completed.returncode, " ".join(command),
                completed.stdout[-3000:], completed.stderr[-3000:])
        )
    return completed


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def probe(path: Path) -> dict:
    completed = run([str(FFPROBE), "-v", "error", "-show_format",
                     "-show_streams", "-of", "json", str(path)])
    return json.loads(completed.stdout)


def duration_of(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def wave_info(path: Path) -> tuple[int, int, int, int]:
    with wave.open(str(path), "rb") as handle:
        return (handle.getnchannels(), handle.getsampwidth(),
                handle.getframerate(), handle.getnframes())


def concat_wavs(parts: list[tuple[Path, float]], output: Path,
                gap_seconds: float = 0.35) -> dict:
    """Concatenate WAVs and pad each scene to a fixed timeline."""
    output.parent.mkdir(parents=True, exist_ok=True)
    params = None
    timeline = []
    with wave.open(str(output), "wb") as out:
        cursor = 0.0
        for path, scene_seconds in parts:
            info = wave_info(path)
            if params is None:
                params = info
                out.setnchannels(info[0])
                out.setsampwidth(info[1])
                out.setframerate(info[2])
            if info[:3] != params[:3]:
                raise RuntimeError("narration WAV formats differ")
            with wave.open(str(path), "rb") as src:
                frames = src.readframes(src.getnframes())
                seconds = src.getnframes() / src.getframerate()
                target_frames = int(round(scene_seconds * src.getframerate()))
                frames = frames[:target_frames * info[1] * info[0]]
                missing = target_frames * info[1] * info[0] - len(frames)
                if missing > 0:
                    frames += b"\x00" * missing
                out.writeframes(frames)
                timeline.append({
                    "path": str(path), "start": round(cursor, 3),
                    "end": round(cursor + scene_seconds, 3),
                    "audio_seconds": round(seconds, 3),
                    "scene_seconds": scene_seconds,
                })
                cursor += scene_seconds
    return {"duration": round(cursor, 3), "timeline": timeline,
            "sample_rate": params[2], "channels": params[0],
            "sample_width": params[1]}


@dataclass(frozen=True)
class ExecutorBinding:
    descriptor: ExecutorDescriptor
    function: Callable[[BlockExecutionRequest], dict]


def _result(request: BlockExecutionRequest, outputs: Mapping[str, Any],
            *, status: BlockStatus = BlockStatus.SUCCEEDED,
            error: ExecutionError | None = None,
            started: str = "", clock: float | None = None) -> BlockExecutionResult:
    from cgkn.execution.contracts import utc_now
    return BlockExecutionResult(
        project_id=request.project_id, run_id=request.run_id,
        attempt_id=request.attempt_id, node_id=request.node_id,
        executor_ref=request.executor_ref, status=status,
        outputs=dict(outputs), error=error,
        started_at=started or utc_now(),
        ended_at=utc_now(),
        duration_ms=max(0, int((time.perf_counter() - (clock or time.perf_counter())) * 1000)),
    )


def _config(request: BlockExecutionRequest) -> dict:
    return dict(request.task_context.node_config)


def _deps(request: BlockExecutionRequest) -> dict:
    return dict(request.task_context.dependency_results)


VIDEO_SCENES = [
    ("intro", "Promotion Studio 是一个本地优先的内容审批与发布工作台。下面用真实界面完成一次演示。"),
    ("projects", "先创建项目与 Campaign。这里选择受众和发布渠道。"),
    ("content", "创建内容后提交审核并批准。审批不是一次性快照：发布时还会重新检查 Campaign、Claim 和媒体。"),
    ("publish", "发布目标只允许本地模拟平台或已授权的 Bluesky。发布后生成可核对的 Receipt。"),
    ("recording", "这是真实的浏览器操作录屏，不是绘制的假界面。"),
    ("qab", "QAB 把时长、音频、字幕、画面内容和视觉评审变成显式义务。技术检查通过，视觉与听感保留为待人工评审。"),
    ("closing", "本轮完成的是技术通过、质量待评审的本地演示，不是正式可信发布。"),
]


def ensure_spec(workdir: Path) -> dict:
    spec_path = workdir / "video_task_spec.json"
    if not spec_path.is_file():
        raise FileNotFoundError("video_task_spec.json is required: " + str(spec_path))
    spec = read_json(spec_path)
    if spec.get("status") != "PROVISIONAL":
        raise ValueError("this integration supports the explicit PROVISIONAL demo spec")
    required = {"duration", "resolution", "fps", "language", "subtitles", "audio",
                "sources", "output"}
    missing = sorted(required - set(spec))
    if missing:
        raise ValueError("video spec missing fields: " + ",".join(missing))
    return spec


def _start_process(command: list[str], cwd: Path, log: Path) -> subprocess.Popen:
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log, "wb")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    return subprocess.Popen(command, cwd=str(cwd), stdout=handle, stderr=subprocess.STDOUT,
                            env=env)


def _wait_http(url: str, timeout: float = 20) -> None:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status < 500:
                    return
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError("service did not become ready: " + url)


def capture_gui(workdir: Path, run_id: str) -> dict:
    from playwright.sync_api import sync_playwright
    evidence = workdir / "evidence"
    gui = evidence / "gui"
    if gui.exists():
        shutil.rmtree(gui)
    gui.mkdir(parents=True)
    data = evidence / "gui_data"
    platform_data = evidence / "platform_data"
    for path in (data, platform_data):
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)

    app_port, platform_port = free_port(), free_port()
    app_log = gui / "app.log"
    platform_log = gui / "platform.log"
    app = _start_process([str(PY), "-B", "-X", "utf8", "main.py", "--serve",
                          "--port", str(app_port), "--data", str(data)],
                         APP_ROOT, app_log)
    platform = _start_process([str(PY), "-B", "-X", "utf8", "serve_platform.py",
                               "--port", str(platform_port), "--data", str(platform_data)],
                              APP_ROOT, platform_log)
    base = f"http://127.0.0.1:{app_port}"
    platform_url = f"http://127.0.0.1:{platform_port}"
    try:
        _wait_http(base + "/health")
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", platform_port), timeout=.2):
                    break
            except OSError:
                time.sleep(.1)
        result = {"base": base, "platform_url": platform_url,
                  "screenshots": [], "console_errors": [], "page_errors": []}
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1600, "height": 900},
                record_video_dir=str(gui / "video"),
                record_video_size={"width": 1600, "height": 900},
            )
            page = context.new_page()
            page.set_default_timeout(15000)
            page.on("pageerror", lambda error: result["page_errors"].append(str(error)))
            page.on("console", lambda message: result["console_errors"].append(
                {"type": message.type, "text": message.text})
                if message.type == "error" else None)
            page.goto(base, wait_until="networkidle")
            page.wait_for_timeout(600)

            def shot(name: str):
                path = gui / name
                page.screenshot(path=str(path), full_page=False)
                result["screenshots"].append({"name": name, "path": str(path),
                                              "sha256": sha256(path)})

            page.locator("#project-name").fill("QAB 视频演示项目 " + run_id)
            page.get_by_role("button", name="Create project", exact=True).click()
            page.wait_for_timeout(700)
            shot("01_projects.png")

            page.get_by_role("button", name="Campaigns", exact=True).click()
            page.wait_for_timeout(500)
            page.locator("#campaign-name").fill("本地演示 Campaign")
            page.locator("#campaign-audience").fill("本地评审者")
            page.locator("#campaign-channels").fill("twitter")
            page.get_by_role("button", name="Create campaign", exact=True).click()
            page.wait_for_timeout(700)
            shot("02_campaigns.png")

            page.get_by_role("button", name="Content", exact=True).click()
            page.wait_for_timeout(800)
            page.locator("#content-text").fill(
                "Promotion Studio 的真实本地发布演示。审批、调度和发布都有可核对的状态。")
            page.locator("#content-channel").select_option("twitter")
            page.get_by_role("button", name="Save content", exact=True).click()
            page.wait_for_timeout(800)
            shot("03_content_draft.png")
            page.get_by_role("button", name="Review", exact=True).click()
            page.wait_for_timeout(500)
            page.get_by_role("button", name="Approve", exact=True).click()
            page.wait_for_timeout(700)
            shot("04_approved.png")
            page.locator("#content-platform-url").fill(platform_url)
            page.get_by_role("button", name="Publish", exact=True).click()
            page.wait_for_timeout(1200)
            shot("05_published.png")

            page.get_by_role("button", name="Receipts/Analytics", exact=True).click()
            page.wait_for_timeout(900)
            shot("06_receipts.png")
            (gui / "page.html").write_text(page.content(), encoding="utf-8")
            result["labels"] = {
                "page_title": page.title(),
                "project_status": page.locator("#project-status").inner_text(),
                "content_status": page.locator("#content-status").inner_text(),
                "receipts": page.locator("#receipts-list").inner_text(),
                "navigation": page.locator("nav").inner_text(),
            }
            result["no_page_errors"] = not result["page_errors"]
            context.close()
            browser.close()
        videos = sorted((gui / "video").glob("*.webm"))
        if not videos:
            raise RuntimeError("Playwright did not produce a recording")
        result["recording"] = {"path": str(videos[0]), "sha256": sha256(videos[0]),
                               "duration": duration_of(videos[0])}
        observation = gui / "gui_observations.json"
        write_json(observation, result)
        result["observations_path"] = str(observation)
        result["observations_sha256"] = sha256(observation)
        return result
    finally:
        for process in (app, platform):
            try:
                process.terminate()
                process.wait(timeout=8)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass


DESIGN_CSS = """
html,body{margin:0;width:1920px;height:1080px;background:#0b1f2a;color:#f8fafc;
font-family:'Microsoft YaHei','Noto Sans SC',sans-serif;overflow:hidden}
.stage{position:relative;width:1920px;height:1080px;padding:70px 90px;box-sizing:border-box;
background:radial-gradient(circle at 82% 18%,#124b55 0,#0b1f2a 48%,#07141c 100%)}
.kicker{font-size:26px;letter-spacing:5px;color:#5eead4;text-transform:uppercase}
h1{font-size:78px;line-height:1.14;margin:20px 0 22px;font-weight:700}
h2{font-size:58px;line-height:1.2;margin:12px 0 20px}
.sub{font-size:30px;color:#94a3b8;line-height:1.5}
.frame{position:absolute;left:90px;right:90px;top:245px;bottom:105px;border:2px solid #1f4b57;
border-radius:22px;overflow:hidden;background:#0e2530;box-shadow:0 32px 90px #0008}
.frame img{width:100%;height:100%;object-fit:cover;object-position:top center}
.caption{position:absolute;left:90px;right:90px;bottom:35px;font-size:25px;color:#94a3b8}
.badge{display:inline-block;padding:8px 18px;border:1px solid #2dd4bf55;border-radius:999px;
background:#2dd4bf18;color:#5eead4;font-size:22px;margin-right:12px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:26px}
.card{border:1px solid #1f4b57;background:#0e2530cc;border-radius:16px;padding:22px 26px;font-size:24px;line-height:1.4}
.card b{color:#5eead4;display:block;font-size:27px;margin-bottom:8px}
.ok{color:#5eead4}.pending{color:#fbbf24}
.footer{position:absolute;right:90px;top:36px;font-size:22px;color:#64748b}
"""


def _data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _slide_html(title: str, kicker: str, image: Path | None = None,
                subtitle: str = "", cards: list[tuple[str, str]] | None = None,
                footer: str = "") -> str:
    body = ""
    if image is not None:
        body += (f'<div class="frame"><img src="{_data_uri(image)}" alt="real app screenshot"></div>')
    elif cards:
        body += '<div class="grid">' + "".join(
            f'<div class="card"><b>{key}</b>{value}</div>' for key, value in cards
        ) + "</div>"
        if subtitle:
            body += f'<div class="sub" style="margin-top:18px">{subtitle}</div>'
    else:
        body += f'<div class="sub">{subtitle}</div>'
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<style>{DESIGN_CSS}</style><body><div class="stage">
<div class="kicker">{kicker}</div><h1>{title}</h1>{body}
<div class="footer">{footer}</div></div></body></html>"""


def design_slides(workdir: Path, gui: dict) -> dict:
    from playwright.sync_api import sync_playwright
    evidence = workdir / "evidence"
    design = evidence / "design"
    design.mkdir(parents=True, exist_ok=True)
    by_name = {item["name"]: Path(item["path"]) for item in gui["screenshots"]}
    slides = []
    specs = [
        ("00_intro", "Promotion Studio", "REAL LOCAL WORKFLOW",
         None, "真实操作 × 质量行为化验收<br>VeriArbor QAB · 技术通过 / 感知评审待人工"),
        ("01_projects", "1. 项目与 Campaign", "PROMOTION STUDIO",
         by_name["02_campaigns.png"], "真实页面：项目、Campaign、受众与渠道"),
        ("02_content", "2. 内容与审批", "CONTINUOUS AUTHORIZATION",
         by_name["04_approved.png"], "审批通过后，发布时仍重新检查依赖状态"),
        ("03_publish", "3. 发布与 Receipt", "LOCAL PUBLISH",
         by_name["06_receipts.png"], "发布结果绑定 Receipt，状态可核对"),
        ("04_qab", "5. QAB 质量义务", "QUALITY ATTRIBUTE BEHAVIOR",
         None, "把质量要求变成可执行、可观察、可失效的证据",
         [("技术", "容器 / 解码 / 时长 / 分辨率 / 音轨"),
          ("内容", "真实 GUI 镜头与关键页面出现"),
          ("字幕", "编码帧内可见、时序与安全区"),
          ("音频", "本地中文旁白非静音"),
          ("视觉", "关键帧联系表 → 待人工评审"),
          ("复用", "字幕局部变更只失效依赖证据")]),
        ("05_closing", "技术通过 · 质量待评审", "SCOPE HONESTY",
         None, "这不是正式可信发布，也不代表所有未知质量风险已消失",
         [("已证明", "真实 Tree/DAG 执行 + 技术/内容/字幕/音频检查"),
          ("未证明", "视觉审美、听感、真实外部平台、P11 信任锚")]),
    ]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        for index, item in enumerate(specs):
            if item[0] == "04_qab":
                name, title, kicker, image, subtitle, cards = item
            else:
                name, title, kicker, image, subtitle = item[:5]
                cards = None
            html = _slide_html(title, kicker, image, subtitle, cards,
                               footer="PROMOTION STUDIO · QAB DEMO · 2026-11-07")
            html_path = design / f"{name}.html"
            png_path = design / f"{name}.png"
            html_path.write_text(html, encoding="utf-8")
            page.set_content(html, wait_until="load")
            page.wait_for_timeout(250)
            page.screenshot(path=str(png_path))
            slides.append({"id": name, "html": str(html_path), "png": str(png_path),
                           "sha256": sha256(png_path)})
        browser.close()
    storyboard = design / "storyboard.html"
    storyboard.write_text(
        "<!doctype html><meta charset=utf-8><title>QAB Storyboard</title>"
        "<body style='background:#0b1f2a;color:#f8fafc;font-family:Microsoft YaHei'>"
        + "".join(f"<section><h2>{s['id']}</h2><img src='{Path(s['png']).name}' "
                  f"style='width:960px'></section>" for s in slides)
        + "<h1>Promotion Studio QAB</h1><p>技术检查与真实 GUI 证据</p></body>",
        encoding="utf-8")
    manifest = {"slides": slides, "storyboard": str(storyboard),
                "storyboard_sha256": sha256(storyboard)}
    write_json(evidence / "design" / "design_manifest.json", manifest)
    manifest["design_manifest_sha256"] = sha256(evidence / "design" / "design_manifest.json")
    return manifest


def synthesize_narration(workdir: Path, scene_texts: list[str]) -> dict:
    audio_dir = workdir / "evidence" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    ps1 = workdir / "trace" / "tts.ps1"
    ps1.parent.mkdir(parents=True, exist_ok=True)
    out_paths = [audio_dir / f"scene_{index:02d}.wav" for index in range(len(scene_texts))]
    escaped = [str(path).replace("'", "''") for path in out_paths]
    texts = [text.replace("'", "''") for text in scene_texts]
    lines = [
        "Add-Type -AssemblyName System.Speech",
        "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer",
        "$speaker.SelectVoice('Microsoft Huihui Desktop')",
        "$speaker.Rate = 2",
        "$speaker.Volume = 100",
        "$outputs = @(" + ",".join("'" + value + "'" for value in escaped) + ")",
        "$texts = @(" + ",".join("'" + value + "'" for value in texts) + ")",
        "for ($i = 0; $i -lt $texts.Count; $i++) {",
        "  $speaker.SetOutputToWaveFile($outputs[$i])",
        "  $speaker.Speak($texts[$i])",
        "}",
        "$speaker.Dispose()",
    ]
    ps1.write_text("\n".join(lines), encoding="utf-8-sig")
    run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
        timeout=180)
    parts = []
    for index, (path, text) in enumerate(zip(out_paths, scene_texts)):
        if not path.is_file():
            raise RuntimeError("TTS did not create " + str(path))
        parts.append((path, duration_of(path)))
    return {"parts": [{"path": str(path), "text": text, "duration": duration}
                      for (path, text), duration in zip(zip(out_paths, scene_texts), [p[1] for p in parts])],
            "voice": "Microsoft Huihui Desktop", "paid_provider": False}


def _wrap_subtitle(text: str, width: int = 24) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]*|[\u4e00-\u9fff]|[\u3000-\u303f，。；：、！？（）“”‘’]|\s+", text)
    lines: list[str] = []
    current = ""
    for token in tokens:
        if not token:
            continue
        if token.isspace():
            if current and not current.endswith(" "):
                current += " "
            continue
        if len(current) + len(token) <= width:
            current += token
        else:
            if current.strip():
                lines.append(current.strip())
            current = token if len(token) <= width else token
    if current.strip():
        lines.append(current.strip())
    if len(lines) > 2:
        lines = [lines[0], "".join(lines[1:])]
    return lines or [text]


def build_captions(workdir: Path, captions_data: list[dict]) -> dict:
    out = workdir / "out" / "demo.srt"
    trace = workdir / "trace" / "captions.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    cues = []
    index = 1
    for scene in captions_data:
        text = str(scene["text"]).strip()
        start = float(scene["start"]) + 0.15
        end = float(scene["end"]) - 0.15
        if end <= start:
            continue
        # Keep the subtitle readable: at most two short lines.
        lines = _wrap_subtitle(text, 24)
        cues.append({"index": index, "start": round(start, 3), "end": round(end, 3),
                     "text": "\n".join(lines), "scene": scene.get("scene", "")})
        index += 1
    def stamp(seconds: float) -> str:
        millis = int(round(seconds * 1000))
        hours, rem = divmod(millis, 3600000)
        minutes, rem = divmod(rem, 60000)
        sec, ms = divmod(rem, 1000)
        return f"{hours:02d}:{minutes:02d}:{sec:02d},{ms:03d}"
    srt = "".join(f"{cue['index']}\n{stamp(cue['start'])} --> {stamp(cue['end'])}\n"
                  f"{cue['text']}\n\n" for cue in cues)
    out.write_text(srt, encoding="utf-8")
    write_json(trace, {"cues": cues, "srt": str(out), "srt_sha256": sha256(out)})
    return {"cues": cues, "srt": str(out), "srt_sha256": sha256(out),
            "captions_json": str(trace)}


def render_draft(workdir: Path, spec: dict, design: dict, timings: dict,
                 recording: dict) -> dict:
    out_dir = workdir / "out"
    scene_dir = workdir / "scenes"
    out_dir.mkdir(parents=True, exist_ok=True)
    if scene_dir.exists():
        shutil.rmtree(scene_dir)
    scene_dir.mkdir(parents=True)
    by_id = {item["id"]: item for item in design["slides"]}
    scene_specs = [
        ("intro", "00_intro", "slide"),
        ("projects", "01_projects", "slide"),
        ("content", "02_content", "slide"),
        ("publish", "03_publish", "slide"),
        ("recording", "recording", "recording"),
        ("qab", "04_qab", "slide"),
        ("closing", "05_closing", "slide"),
    ]
    manifest = []
    concat_path = workdir / "trace" / "concat.txt"
    concat_lines = []
    cursor = 0.0
    for scene_id, source_id, kind in scene_specs:
        timing = next(item for item in timings["timeline"] if item["scene"] == scene_id)
        duration = float(timing["duration"])
        scene_path = scene_dir / f"{scene_id}.mp4"
        if kind == "slide":
            source = Path(by_id[source_id]["png"])
            vf = ("scale=2016:1134,zoompan=z='min(zoom+0.00055,1.08)':"
                  "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1920x1080:fps=30,"
                  "format=yuv420p")
            command = [str(FFMPEG), "-y", "-loop", "1", "-i", str(source),
                       "-t", f"{duration:.3f}", "-vf", vf, "-an",
                       "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                       "-pix_fmt", "yuv420p", str(scene_path)]
        else:
            vf = "scale=1600:900,pad=1920:1080:160:90:color=0x0b1f2a,fps=30,format=yuv420p"
            command = [str(FFMPEG), "-y", "-stream_loop", "-1",
                       "-i", recording["path"], "-t", f"{duration:.3f}",
                       "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast",
                       "-crf", "20", "-pix_fmt", "yuv420p", str(scene_path)]
        run(command, timeout=180)
        concat_lines.append("file '" + str(scene_path).replace("'", "'\\''") + "'")
        manifest.append({"scene": scene_id, "kind": kind, "start": round(cursor, 3),
                         "end": round(cursor + duration, 3), "duration": duration,
                         "source": source_id, "scene_path": str(scene_path),
                         "sha256": sha256(scene_path)})
        cursor += duration
    concat_path.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
    draft = out_dir / "draft_no_subs.mp4"
    run([str(FFMPEG), "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path),
         "-c", "copy", str(draft)], timeout=300)
    manifest_path = workdir / "trace" / "shot_manifest.json"
    write_json(manifest_path, {"scenes": manifest, "draft": str(draft),
                               "draft_sha256": sha256(draft), "duration": round(cursor, 3)})
    return {"draft": str(draft), "draft_sha256": sha256(draft),
            "shot_manifest": str(manifest_path),
            "shot_manifest_sha256": sha256(manifest_path), "duration": round(cursor, 3)}


def mux_final(workdir: Path, draft: Path, narration: Path, srt: Path,
              output: Path) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    style = ("FontName=Microsoft YaHei,FontSize=16,PrimaryColour=&H00FFFFFF,"
             "OutlineColour=&H00101820,Outline=1,Shadow=0,MarginV=28,Alignment=2")
    relative_srt = os.path.relpath(srt, workdir).replace("\\", "/")
    # Relative filter paths avoid Windows drive-colon escaping in ffmpeg filters.
    command = [str(FFMPEG), "-y", "-i", str(draft), "-i", str(narration),
               "-vf", f"subtitles={relative_srt}:original_size=1920x1080:force_style='{style}'",
               "-c:v", "libx264", "-preset", "medium", "-crf", "20",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
               "-movflags", "+faststart", "-shortest", str(output)]
    run(command, cwd=workdir, timeout=300)
    return {"final": str(output), "final_sha256": sha256(output),
            "duration": duration_of(output)}


def _write_checker(workdir: Path, name: str, value: dict) -> None:
    write_json(workdir / "evidence" / "results" / (name + ".json"), value)


def check_technical(workdir: Path, final: Path, spec: dict,
                    ffprobe_bin: str | Path = FFPROBE) -> dict:
    try:
        completed = run([str(ffprobe_bin), "-v", "error", "-show_format",
                         "-show_streams", "-of", "json", str(final)], check=False)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "ffprobe failed")
        info = json.loads(completed.stdout)
        streams = info.get("streams", [])
        video = next((item for item in streams if item.get("codec_type") == "video"), None)
        audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
        duration = float(info.get("format", {}).get("duration", 0))
        decoded = run([str(FFMPEG), "-v", "error", "-xerror", "-i", str(final),
                       "-map", "0:v:0", "-map", "0:a?", "-f", "null", "-"],
                      check=False, timeout=300)
        spec_duration = spec["duration"]
        expected_width = int(spec["resolution"]["width"])
        expected_height = int(spec["resolution"]["height"])
        checks = {
            "decoded_to_end": decoded.returncode == 0,
            "duration_in_spec": spec_duration["min_seconds"] <= duration <= spec_duration["max_seconds"],
            "h264": bool(video and video.get("codec_name") == "h264"),
            "resolution_matches_spec": bool(video and video.get("width") == expected_width
                                            and video.get("height") == expected_height),
            "audio_stream": audio is not None and audio.get("codec_name") == "aac",
            "fps_near_30": bool(video and abs(
                float(video.get("avg_frame_rate", "0/1").split("/")[0]) /
                max(1, float(video.get("avg_frame_rate", "0/1").split("/")[1])) - 30) < 1.0),
        }
        status = "PASS" if all(checks.values()) else "FAIL"
        value = {
            "status": status, "checks": checks, "duration": duration,
            "video": {k: video.get(k) for k in ("codec_name", "width", "height", "avg_frame_rate")} if video else None,
            "audio": {k: audio.get(k) for k in ("codec_name", "channels", "sample_rate")} if audio else None,
            "obligations": ["video.container_decodable", "video.duration",
                            "video.resolution", "video.final_audio_stream"],
            "object_versions": {"final.mp4": sha256(final)},
            "checker_versions": {"technical@1": "1"},
            "evidence_refs": ["evidence/results/technical.json"],
            "metrics": {"decode_exit": decoded.returncode,
                        "format_duration": duration},
        }
        _write_checker(workdir, "technical", value)
        return value
    except Exception as exc:
        value = {"status": "ERROR", "error": repr(exc),
                 "obligations": ["video.container_decodable", "video.duration",
                                 "video.resolution", "video.final_audio_stream"],
                 "object_versions": {"final.mp4": sha256(final) if final.is_file() else ""},
                 "checker_versions": {"technical@1": "1"},
                 "evidence_refs": ["evidence/results/technical.json"]}
        _write_checker(workdir, "technical", value)
        return value


def check_audio(workdir: Path, narration: Path, spec: dict,
                audio_path: Path | None = None) -> dict:
    path = audio_path or narration
    try:
        completed = run([str(FFMPEG), "-hide_banner", "-i", str(path),
                         "-af", "volumedetect", "-f", "null", "-"], check=False)
        text = completed.stderr
        mean = re.search(r"mean_volume:\s*(-?[0-9.]+) dB", text)
        peak = re.search(r"max_volume:\s*(-?[0-9.]+) dB", text)
        mean_value = float(mean.group(1)) if mean else -999.0
        peak_value = float(peak.group(1)) if peak else -999.0
        seconds = duration_of(path)
        checks = {
            "has_audio_duration": seconds >= 5.0,
            "not_all_silent": mean_value > -45.0 and peak_value > -12.0,
            "no_clipping": peak_value <= 0.0,
        }
        status = "PASS" if all(checks.values()) else "FAIL"
        value = {
            "status": status, "checks": checks, "mean_volume_db": mean_value,
            "max_volume_db": peak_value, "duration": seconds,
            "obligations": ["video.audio_narration"],
            "object_versions": {"narration.wav": sha256(narration)},
            "checker_versions": {"audio@1": "1"},
            "evidence_refs": ["evidence/results/audio.json"],
            "metrics": {"mean_volume_db": mean_value, "max_volume_db": peak_value},
        }
        _write_checker(workdir, "audio", value)
        return value
    except Exception as exc:
        value = {"status": "ERROR", "error": repr(exc),
                 "obligations": ["video.audio_narration"],
                 "object_versions": {"narration.wav": sha256(narration) if narration.is_file() else ""},
                 "checker_versions": {"audio@1": "1"},
                 "evidence_refs": ["evidence/results/audio.json"]}
        _write_checker(workdir, "audio", value)
        return value


def _parse_srt(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.splitlines()
        if len(lines) < 3 or "-" not in lines[1]:
            continue
        match = re.match(r"(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)", lines[1])
        if not match:
            continue
        values = [int(item) for item in match.groups()]
        start = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / 1000
        end = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / 1000
        cues.append({"start": start, "end": end, "text": "\n".join(lines[2:])})
    return cues


def _frame_stats(video: Path, at: float) -> tuple[int, float]:
    completed = run([str(FFMPEG), "-hide_banner", "-ss", f"{at:.3f}", "-i", str(video),
                     "-frames:v", "1", "-vf",
                     "crop=1920:260:0:780,signalstats,metadata=print",
                     "-f", "null", "-"], check=False)
    ymax_values = [int(item) for item in re.findall(
        r"lavfi\.signalstats\.YMAX=(\d+)", completed.stderr)]
    yavg_values = [float(item) for item in re.findall(
        r"lavfi\.signalstats\.YAVG=([0-9.]+)", completed.stderr)]
    return (max(ymax_values) if ymax_values else -1,
            max(yavg_values) if yavg_values else -1.0)


def _frame_ymax(video: Path, at: float) -> int:
    return _frame_stats(video, at)[0]


def check_subtitles(workdir: Path, final: Path, srt: Path) -> dict:
    try:
        cues = _parse_srt(srt)
        duration = duration_of(final)
        checks = {
            "cues_present": len(cues) >= 5,
            "cues_in_duration": bool(cues) and cues[-1]["end"] <= duration + 0.05,
            "nonempty_text": bool(cues) and all(item["text"].strip() for item in cues),
            "line_length_safe": bool(cues) and all(
                len(line) <= 42 for item in cues for line in item["text"].splitlines()),
        }
        cue_frame = -1
        cue_yavg = -1.0
        base_frame = -1
        if cues:
            cue_frame, cue_yavg = _frame_stats(final, cues[0]["start"] + 0.2)
            base = max(0.0, cues[0]["start"] - 0.1)
            base_frame, _ = _frame_stats(final, base)
        checks["encoded_frame_has_bright_text"] = cue_frame > 180 and cue_frame > base_frame + 20
        # Reject overbearing subtitle fills: readable text has bright glyphs but
        # the safe-area band is not mostly white.
        checks["subtitle_band_not_overfilled"] = 0 < cue_yavg < 70
        status = "PASS" if all(checks.values()) else "FAIL"
        value = {
            "status": status, "checks": checks, "cue_count": len(cues),
            "cue_ymax": cue_frame, "cue_yavg": cue_yavg, "base_ymax": base_frame,
            "duration": duration,
            "obligations": ["video.subtitles_burned"],
            "object_versions": {"final.mp4": sha256(final), "demo.srt": sha256(srt)},
            "checker_versions": {"subtitle@1": "1"},
            "evidence_refs": ["evidence/results/subtitle.json"],
            "metrics": {"cue_ymax": cue_frame, "base_ymax": base_frame},
        }
        _write_checker(workdir, "subtitle", value)
        return value
    except Exception as exc:
        value = {"status": "ERROR", "error": repr(exc),
                 "obligations": ["video.subtitles_burned"],
                 "object_versions": {"final.mp4": sha256(final) if final.is_file() else "",
                                     "demo.srt": sha256(srt) if srt.is_file() else ""},
                 "checker_versions": {"subtitle@1": "1"},
                 "evidence_refs": ["evidence/results/subtitle.json"]}
        _write_checker(workdir, "subtitle", value)
        return value


def _ssim(frame: Path, reference: Path) -> float:
    completed = run([str(FFMPEG), "-hide_banner", "-i", str(frame),
                     "-i", str(reference), "-lavfi", "ssim", "-f", "null", "-"],
                    check=False)
    matches = re.findall(r"All:([0-9.]+)", completed.stderr)
    return float(matches[-1]) if matches else 0.0


def check_content(workdir: Path, final: Path, shot_manifest: Path,
                  design: dict) -> dict:
    try:
        manifest = read_json(shot_manifest)
        slides = {item["id"]: Path(item["png"]) for item in design["slides"]}
        video_duration = duration_of(final)
        frame_dir = workdir / "evidence" / "frames"
        frame_dir.mkdir(parents=True, exist_ok=True)
        measurements = []
        passed = 0
        for scene in manifest["scenes"]:
            at = (float(scene["start"]) + float(scene["end"])) / 2
            if at >= video_duration - 0.1:
                measurements.append({"scene": scene["scene"],
                                     "error": "scene_time_outside_video",
                                     "video_duration": video_duration})
                continue
            frame = frame_dir / (scene["scene"] + ".png")
            if frame.exists():
                frame.unlink()
            run([str(FFMPEG), "-y", "-ss", f"{at:.3f}", "-i", str(final),
                 "-frames:v", "1", str(frame)], timeout=60)
            if not frame.is_file():
                measurements.append({"scene": scene["scene"],
                                     "error": "frame_not_extracted"})
                continue
            if scene["kind"] == "slide":
                score = _ssim(frame, slides[scene["source"]])
                measurements.append({"scene": scene["scene"], "type": "slide_ssim",
                                     "score": score})
                if score >= 0.45:
                    passed += 1
            else:
                stats = run([str(FFMPEG), "-hide_banner", "-i", str(frame),
                             "-vf", "signalstats,metadata=print", "-f", "null", "-"],
                            check=False)
                yavg = re.findall(r"lavfi\.signalstats\.YAVG=([0-9.]+)", stats.stderr)
                ymax = re.findall(r"lavfi\.signalstats\.YMAX=([0-9.]+)", stats.stderr)
                measurements.append({"scene": scene["scene"], "type": "recording_luma",
                                     "yavg": float(yavg[-1]) if yavg else -1,
                                     "ymax": float(ymax[-1]) if ymax else -1})
                if yavg and float(yavg[-1]) > 10 and ymax and float(ymax[-1]) > 80:
                    passed += 1
        checks = {"at_least_three_real_scenes": passed >= 3,
                  "recordings_and_slides_present": len(measurements) >= 6,
                  "all_scene_times_inside_video": len(measurements) == len(manifest["scenes"])
                  and all("error" not in item for item in measurements)}
        status = "PASS" if all(checks.values()) else "FAIL"
        value = {
            "status": status, "checks": checks, "measurements": measurements,
            "obligations": ["video.content_real_gui"],
            "object_versions": {"final.mp4": sha256(final),
                                "shot_manifest.json": sha256(shot_manifest)},
            "checker_versions": {"content@1": "1"},
            "evidence_refs": ["evidence/results/content.json"],
            "metrics": {"real_scene_count": passed},
        }
        _write_checker(workdir, "content", value)
        return value
    except Exception as exc:
        value = {"status": "ERROR", "error": repr(exc),
                 "obligations": ["video.content_real_gui"],
                 "object_versions": {"final.mp4": sha256(final) if final.is_file() else ""},
                 "checker_versions": {"content@1": "1"},
                 "evidence_refs": ["evidence/results/content.json"]}
        _write_checker(workdir, "content", value)
        return value


def check_gui(workdir: Path, observations: Path) -> dict:
    try:
        data = read_json(observations)
        labels = data.get("labels", {})
        text = " ".join(str(value) for value in labels.values())
        checks = {
            "no_page_errors": data.get("no_page_errors") is True,
            "promotion_studio_visible": "Promotion Studio" in text,
            "content_visible": "Content" in text,
            "receipt_visible": "Receipt" in text,
            "published_receipt": "PUBLISHED" in labels.get("receipts", ""),
            "six_screenshots": len(data.get("screenshots", [])) >= 6,
            "recording_present": bool(data.get("recording", {}).get("path")),
        }
        status = "PASS" if all(checks.values()) else "FAIL"
        value = {"status": status, "checks": checks,
                 "obligations": ["gui.key_pages"],
                 "object_versions": {"gui_observations.json": sha256(observations)},
                 "checker_versions": {"gui@1": "1"},
                 "evidence_refs": ["evidence/results/gui.json"]}
        _write_checker(workdir, "gui", value)
        return value
    except Exception as exc:
        value = {"status": "ERROR", "error": repr(exc), "obligations": ["gui.key_pages"],
                 "object_versions": {"gui_observations.json": ""},
                 "checker_versions": {"gui@1": "1"},
                 "evidence_refs": ["evidence/results/gui.json"]}
        _write_checker(workdir, "gui", value)
        return value


def check_html(workdir: Path, storyboard: Path) -> dict:
    try:
        text = re.sub(r"<[^>]+>", " ", storyboard.read_text(encoding="utf-8"))
        checks = {
            "title_present": "Promotion Studio" in text,
            "qab_present": "QAB" in text,
            "technical_text_present": "技术检查" in text,
            "at_least_five_images": storyboard.read_text(encoding="utf-8").count("<img") >= 5,
        }
        status = "PASS" if all(checks.values()) else "FAIL"
        value = {"status": status, "checks": checks,
                 "obligations": ["html.storyboard_text"],
                 "object_versions": {"storyboard.html": sha256(storyboard)},
                 "checker_versions": {"html@1": "1"},
                 "evidence_refs": ["evidence/results/html.json"]}
        _write_checker(workdir, "html", value)
        return value
    except Exception as exc:
        value = {"status": "ERROR", "error": repr(exc),
                 "obligations": ["html.storyboard_text"],
                 "object_versions": {"storyboard.html": ""},
                 "checker_versions": {"html@1": "1"},
                 "evidence_refs": ["evidence/results/html.json"]}
        _write_checker(workdir, "html", value)
        return value


def check_visual(workdir: Path, final: Path) -> dict:
    contact = workdir / "evidence" / "contact_sheet.png"
    contact.parent.mkdir(parents=True, exist_ok=True)
    completed = run([str(FFMPEG), "-y", "-i", str(final), "-vf",
                     "fps=1/5,scale=480:-1,tile=4x2:padding=8:margin=8",
                     "-frames:v", "1", str(contact)], check=False, timeout=120)
    status = "PENDING_REVIEW" if completed.returncode == 0 and contact.is_file() else "ERROR"
    value = {"status": status,
             "obligations": ["video.visual_quality"],
             "object_versions": {"final.mp4": sha256(final),
                                 "contact_sheet.png": sha256(contact) if contact.is_file() else ""},
             "checker_versions": {"visual@1": "1"},
             "evidence_refs": ["evidence/contact_sheet.png"],
             "pending_reason": "human visual review has not been performed"}
    _write_checker(workdir, "visual", value)
    return value


def video_obligations(spec: dict) -> QualityPlan:
    audio_required = spec.get("audio", {}).get("mode") == "required"
    def ob(oid, subject, checker, kind=QualityKind.DETERMINISTIC,
           required=True, behavior="", criterion="", basis="", scope=("final_mp4",)):
        return QualityObligation(
            id=oid, version="1", source="provisional-video-spec",
            scope=scope, trigger=("video",), behavior=behavior,
            observable=behavior, criterion=criterion, criterion_basis=basis,
            checker=checker, checker_version="1", subject_refs=(subject,),
            required=required, kind=kind,
            invalidation_keys=(subject,),
            failure_owner="promotion.video",
            pending_review_reason=(
                "human visual/audio review has not been performed"
                if kind in (QualityKind.MANUAL, QualityKind.PERCEPTUAL) else ""),
        )
    values = [
        ob("video.container_decodable", "final.mp4", "technical@1",
           behavior="final container decodes from start to end",
           criterion="ffmpeg -xerror decodes with exit 0",
           basis="provisional technical gate"),
        ob("video.duration", "final.mp4", "technical@1",
           behavior="final duration matches frozen specification",
           criterion="30 <= duration <= 60 seconds",
           basis="provisional spec"),
        ob("video.resolution", "final.mp4", "technical@1",
           behavior="final is H.264 1920x1080 near 30 fps",
           criterion="codec h264, 1920x1080, ~30 fps",
           basis="provisional spec"),
        ob("video.final_audio_stream", "final.mp4", "technical@1",
           behavior="final carries an AAC audio stream",
           criterion="audio stream codec aac",
           basis="provisional spec"),
        ob("video.content_real_gui", "final.mp4", "content@1",
           kind=QualityKind.MEASURED,
           behavior="real GUI slides and browser recording appear in final",
           criterion=">=3 real scenes pass similarity/luma checks",
           basis="provisional content gate"),
        ob("video.subtitles_burned", "final.mp4", "subtitle@1",
           kind=QualityKind.MEASURED,
           behavior="subtitles are readable in encoded frames",
           criterion="cue timing/text safe and cue frame has bright text",
           basis="provisional subtitle gate"),
        ob("video.audio_narration", "narration.wav", "audio@1",
           kind=QualityKind.MEASURED, required=audio_required,
           behavior="local Chinese narration is present and non-silent",
           criterion="mean > -45 dB and peak > -12 dB",
           basis="provisional audio gate"),
        ob("gui.key_pages", "gui_observations.json", "gui@1",
           behavior="real browser pages show key workflow labels and PUBLISHED receipt",
           criterion="labels present, no page errors, 6 screenshots",
           basis="provisional GUI gate"),
        ob("html.storyboard_text", "storyboard.html", "html@1",
           behavior="storyboard HTML renders required text",
           criterion="title, QAB and technical text present",
           basis="second-domain HTML control"),
        ob("video.visual_quality", "contact_sheet.png", "visual@1",
           kind=QualityKind.PERCEPTUAL,
           behavior="visual composition is acceptable to a human reviewer",
           criterion="human review required",
           basis="perceptual review not automated"),
        ob("video.audio_intelligibility", "narration.wav", "audio_human@1",
           kind=QualityKind.PERCEPTUAL,
           behavior="narration is intelligible and correctly aligned",
           criterion="human listening / ASR review required",
           basis="perceptual review not automated"),
    ]
    applicability = {item.id: True for item in values}
    na = {}
    if not audio_required:
        applicability["video.audio_narration"] = False
        na["video.audio_narration"] = "task declares audio optional/silent"
    return QualityPlan(tuple(values), applicability=applicability, na_reasons=na)


def _quality_evidence(results: Mapping[str, Mapping[str, Any]],
                      obligations: QualityPlan) -> list[QualityEvidence]:
    evidence: list[QualityEvidence] = []
    checker_to_node = {
        "technical@1": "technical", "content@1": "content",
        "subtitle@1": "subtitle", "audio@1": "audio",
        "gui@1": "gui_layout", "html@1": "html_control",
    }
    for obligation in obligations.obligations:
        node_id = checker_to_node.get(obligation.checker)
        if node_id is None:
            continue
        result = results.get(node_id, {})
        status = str(result.get("status", "ERROR"))
        verdict = {"PASS": QualityVerdict.PASS, "FAIL": QualityVerdict.FAIL,
                   "ERROR": QualityVerdict.ERROR}.get(status, QualityVerdict.ERROR)
        evidence.append(QualityEvidence(
            obligation_id=obligation.id, obligation_version=obligation.version,
            verdict=verdict,
            object_versions={k: str(v) for k, v in result.get("object_versions", {}).items()},
            checker_versions={k: str(v) for k, v in result.get("checker_versions", {}).items()},
            evidence_refs=tuple(result.get("evidence_refs", ())),
            measured=dict(result.get("metrics", {})),
            notes=str(result.get("error", "")),
        ))
    # Perceptual checks are recorded as pending review, never as PASS.
    final_hash = str(results.get("technical", {}).get("object_versions", {}).get("final.mp4", ""))
    contact = str(results.get("visual", {}).get("object_versions", {}).get("contact_sheet.png", ""))
    narration = str(results.get("audio", {}).get("object_versions", {}).get("narration.wav", ""))
    for oid, subject, value, checker in (
        ("video.visual_quality", "contact_sheet.png", contact, "visual@1"),
        ("video.audio_intelligibility", "narration.wav", narration, "audio_human@1"),
    ):
        evidence.append(QualityEvidence(
            obligation_id=oid, obligation_version="1",
            verdict=QualityVerdict.PENDING_REVIEW,
            object_versions={subject: value}, checker_versions={checker: "1"},
            evidence_refs=("evidence/results/review_pending.json",),
            notes="human review pending",
        ))
    return evidence


def qab_acceptance(workdir: Path, spec: dict, results: Mapping[str, Mapping[str, Any]]) -> dict:
    plan = video_obligations(spec)
    evidence = _quality_evidence(results, plan)
    object_versions = {
        "final.mp4": str(results.get("technical", {}).get("object_versions", {}).get("final.mp4", "")),
        "narration.wav": str(results.get("audio", {}).get("object_versions", {}).get("narration.wav", "")),
        "demo.srt": str(results.get("subtitle", {}).get("object_versions", {}).get("demo.srt", "")),
        "shot_manifest.json": str(results.get("content", {}).get("object_versions", {}).get("shot_manifest.json", "")),
        "gui_observations.json": str(results.get("gui_layout", {}).get("object_versions", {}).get("gui_observations.json", "")),
        "storyboard.html": str(results.get("html_control", {}).get("object_versions", {}).get("storyboard.html", "")),
        "contact_sheet.png": str(results.get("visual", {}).get("object_versions", {}).get("contact_sheet.png", "")),
    }
    checker_versions = {
        "technical@1": "1", "content@1": "1", "subtitle@1": "1",
        "audio@1": "1", "gui@1": "1", "html@1": "1",
        "visual@1": "1", "audio_human@1": "1",
    }
    report = plan.coverage(evidence, object_versions=object_versions,
                           checker_versions=checker_versions)
    technical_plan = QualityPlan(tuple(
        item for item in plan.obligations
        if item.kind is not QualityKind.PERCEPTUAL and item.required))
    technical_report = technical_plan.coverage(
        evidence, object_versions=object_versions, checker_versions=checker_versions)
    technical_status = technical_report.status.value
    overall = report.status.value
    acceptance = {
        "kind": "QABGoalAcceptance",
        "schema_version": "1.0",
        "status": ("TECHNICAL_PASS_QUALITY_PENDING_REVIEW"
                   if technical_status == "PASS" and overall == "PENDING_REVIEW"
                   else overall),
        "technical_status": technical_status,
        "overall_status": overall,
        "formal_trust": False,
        "required_obligations": list(plan.required_ids),
        "missing_required": list(report.missing_required),
        "pending_review": list(report.pending_review),
        "report": report.as_dict(),
        "technical_report": technical_report.as_dict(),
        "object_versions": object_versions,
        "checker_versions": checker_versions,
        "scope_note": "local QAB acceptance; not a formal P11 trust-anchored delivery",
    }
    write_json(workdir / "trace" / "qab_report.json", {
        "plan": plan.as_dict(), "evidence": [item.as_dict() for item in evidence],
        "report": report.as_dict(), "technical_report": technical_report.as_dict(),
    })
    write_json(workdir / "trace" / "goal_acceptance.json", acceptance)
    return acceptance


def _contract(node_id: str, goal: str, kind: str, scope: list[str],
              acceptance: list[str], checker: str, executor: str,
              dependencies: list[str], **details) -> dict:
    return build_leaf_contract(
        goal=goal, kind=kind, scope=scope, acceptance=acceptance,
        checker=checker, output_identity=node_id, effect_domains=["filesystem"],
        executor=executor, dependencies=dependencies, **details,
    )


def _node(node_id: str, capability: str, dependencies: list[str],
          contract: dict, workdir: Path, run_id: str) -> CapabilityNode:
    return CapabilityNode(
        node_id, parent_id="video", capability_ref=capability,
        depends_on=tuple(dependencies),
        config={"executor_ref": capability, "workdir": str(workdir),
                "run_id": run_id, "leaf_contract": contract},
    )


def build_video_tree(workdir: Path, spec: dict, run_id: str) -> tuple[CapabilityTree, Any]:
    nodes = [CapabilityNode("video", capability_ref="")]
    nodes.append(_node(
        "spec", "promotion.video.spec@1", [],
        _contract("spec", "freeze the video task specification", "IMPLEMENTATION",
                  ["video_task_spec.json", "VIDEO_GOAL_RESOLUTION.md"],
                  ["video.spec.frozen"], "promotion.checker.spec@1",
                  "promotion.video.spec@1", [],
                  expected_delta="write canonical spec and goal resolution"),
        workdir, run_id))
    nodes.append(_node(
        "gui", "promotion.video.gui@1", ["spec"],
        _contract("gui", "capture the real Promotion Studio workflow", "IMPLEMENTATION",
                  ["evidence/gui/01_projects.png", "evidence/gui/02_campaigns.png",
                   "evidence/gui/03_content_draft.png", "evidence/gui/04_approved.png",
                   "evidence/gui/05_published.png", "evidence/gui/06_receipts.png",
                   "evidence/gui/page.html", "evidence/gui/gui_observations.json"],
                  ["gui.key_pages"], "promotion.checker.gui@1",
                  "promotion.video.gui@1", ["spec"],
                  expected_delta="real browser screenshots and a real recording"),
        workdir, run_id))
    nodes.append(_node(
        "design", "promotion.video.design@1", ["gui"],
        _contract("design", "apply the frozen visual design baseline to real captures",
                  "IMPLEMENTATION",
                  ["evidence/design/00_intro.png", "evidence/design/01_projects.png",
                   "evidence/design/02_content.png", "evidence/design/03_publish.png",
                   "evidence/design/04_qab.png", "evidence/design/05_closing.png",
                   "evidence/design/storyboard.html", "evidence/design/design_manifest.json"],
                  ["html.storyboard_text"], "promotion.checker.design@1",
                  "promotion.video.design@1", ["gui"],
                  expected_delta="styled slides and a storyboard from real captures"),
        workdir, run_id))
    nodes.append(_node(
        "gui_layout", "promotion.video.gui-check@1", ["gui"],
        _contract("gui_layout", "inspect real GUI labels and browser errors", "TEST",
                  ["evidence/gui/gui_observations.json", "evidence/results/gui.json"],
                  ["gui.key_pages"], "promotion.checker.gui@1",
                  "promotion.video.gui-check@1", ["gui"],
                  subject="gui_observations.json",
                  expected_observation="key labels, no page errors, PUBLISHED receipt",
                  pass_fail_rule="all key labels and receipt state present"),
        workdir, run_id))
    nodes.append(_node(
        "script", "promotion.video.script@1", ["spec", "gui", "design"],
        _contract("script", "write the scene plan and narration text", "IMPLEMENTATION",
                  ["trace/scenes.json", "trace/narration_text.json"],
                  ["video.script.plan"], "promotion.checker.script@1",
                  "promotion.video.script@1", ["spec", "gui", "design"],
                  expected_delta="scene plan and Chinese narration text"),
        workdir, run_id))
    nodes.append(_node(
        "tts", "promotion.video.tts@1", ["script"],
        _contract("tts", "synthesize local Chinese narration", "IMPLEMENTATION",
                  ["evidence/audio/narration.wav", "trace/tts_manifest.json"],
                  ["video.audio_narration"], "promotion.checker.tts@1",
                  "promotion.video.tts@1", ["script"],
                  expected_delta="narration.wav and scene timings"),
        workdir, run_id))
    nodes.append(_node(
        "captions", "promotion.video.captions@1", ["tts", "script"],
        _contract("captions", "create deterministic Chinese subtitles", "IMPLEMENTATION",
                  ["out/demo.srt", "trace/captions.json"],
                  ["video.subtitles_burned"], "promotion.checker.captions@1",
                  "promotion.video.captions@1", ["tts", "script"],
                  expected_delta="SRT cues tied to narration timing"),
        workdir, run_id))
    nodes.append(_node(
        "render", "promotion.video.render@1", ["gui", "design", "tts", "script"],
        _contract("render", "compose the draft video from real captures and slides",
                  "IMPLEMENTATION",
                  ["out/draft_no_subs.mp4", "trace/shot_manifest.json", "trace/scenes.json"],
                  ["video.content_real_gui"], "promotion.checker.render@1",
                  "promotion.video.render@1", ["gui", "design", "tts", "script"],
                  expected_delta="decodable draft video and shot manifest"),
        workdir, run_id))
    nodes.append(_node(
        "mux", "promotion.video.mux@1", ["render", "captions", "tts"],
        _contract("mux", "burn subtitles and mux narration into final.mp4", "IMPLEMENTATION",
                  ["out/final.mp4", "out/demo.srt", "evidence/audio/narration.wav"],
                  ["video.subtitles_burned", "video.final_audio_stream"],
                  "promotion.checker.mux@1", "promotion.video.mux@1",
                  ["render", "captions", "tts"],
                  expected_delta="final H.264/AAC MP4 with burned subtitles"),
        workdir, run_id))
    nodes.append(_node(
        "technical", "promotion.video.technical@1", ["mux"],
        _contract("technical", "measure container, decode, duration and codecs", "TEST",
                  ["out/final.mp4", "evidence/results/technical.json"],
                  ["video.container_decodable", "video.duration", "video.resolution",
                   "video.final_audio_stream"], "promotion.checker.technical@1",
                  "promotion.video.technical@1", ["mux"],
                  subject="final.mp4", expected_observation="decodable 1920x1080 H.264/AAC, 30-60s",
                  pass_fail_rule="all technical checks true"),
        workdir, run_id))
    nodes.append(_node(
        "content", "promotion.video.content@1", ["mux", "render"],
        _contract("content", "verify real GUI slides and recording in final frames", "TEST",
                  ["out/final.mp4", "trace/shot_manifest.json", "evidence/results/content.json"],
                  ["video.content_real_gui"], "promotion.checker.content@1",
                  "promotion.video.content@1", ["mux", "render"],
                  subject="final.mp4", expected_observation="real scenes visible at declared times",
                  pass_fail_rule="at least three real scenes pass"),
        workdir, run_id))
    nodes.append(_node(
        "subtitle", "promotion.video.subtitle@1", ["mux", "captions"],
        _contract("subtitle", "inspect encoded subtitle frames and SRT safety", "TEST",
                  ["out/final.mp4", "out/demo.srt", "evidence/results/subtitle.json"],
                  ["video.subtitles_burned"], "promotion.checker.subtitle@1",
                  "promotion.video.subtitle@1", ["mux", "captions"],
                  subject="final.mp4", expected_observation="bright subtitle text at cue frame",
                  pass_fail_rule="timing and encoded-frame checks true"),
        workdir, run_id))
    nodes.append(_node(
        "audio", "promotion.video.audio@1", ["tts"],
        _contract("audio", "measure narration presence and loudness", "TEST",
                  ["evidence/audio/narration.wav", "evidence/results/audio.json"],
                  ["video.audio_narration"], "promotion.checker.audio@1",
                  "promotion.video.audio@1", ["tts"],
                  subject="narration.wav", expected_observation="non-silent local narration",
                  pass_fail_rule="mean > -45 dB and peak > -12 dB"),
        workdir, run_id))
    nodes.append(_node(
        "visual", "promotion.video.visual@1", ["mux"],
        _contract("visual", "export key frames for human visual review", "INSPECTION",
                  ["out/final.mp4", "evidence/contact_sheet.png", "evidence/results/visual.json"],
                  ["video.visual_quality"], "promotion.checker.visual@1",
                  "promotion.video.visual@1", ["mux"],
                  subject="contact_sheet.png", expected_observation="key frame contact sheet",
                  pass_fail_rule="contact sheet generated; aesthetic PASS is human-only"),
        workdir, run_id))
    nodes.append(_node(
        "html_control", "promotion.video.html@1", ["design"],
        _contract("html_control", "verify storyboard HTML text rendering", "TEST",
                  ["evidence/design/storyboard.html", "evidence/results/html.json"],
                  ["html.storyboard_text"], "promotion.checker.html@1",
                  "promotion.video.html@1", ["design"],
                  subject="storyboard.html", expected_observation="title/QAB/technical text present",
                  pass_fail_rule="all text checks true"),
        workdir, run_id))
    nodes.append(_node(
        "review", "promotion.video.review@1", ["visual", "audio"],
        _contract("review", "record perceptual review as pending, not PASS", "INSPECTION",
                  ["evidence/results/review_pending.json"],
                  ["video.visual_quality", "video.audio_intelligibility"],
                  "promotion.checker.audio_human@1", "promotion.video.review@1",
                  ["visual", "audio"],
                  subject="review_pending.json",
                  expected_observation="human visual/listening review pending",
                  pass_fail_rule="PENDING_REVIEW is not a quality PASS"),
        workdir, run_id))
    nodes.append(_node(
        "qab", "promotion.video.qab@1",
        ["technical", "content", "subtitle", "audio", "visual", "gui_layout",
         "html_control", "review"],
        _contract("qab", "compute required quality-obligation coverage", "INSPECTION",
                  ["trace/qab_report.json", "trace/goal_acceptance.json"],
                  ["video.container_decodable", "video.duration", "video.resolution",
                   "video.final_audio_stream", "video.content_real_gui",
                   "video.subtitles_burned", "video.audio_narration",
                   "gui.key_pages", "html.storyboard_text", "video.visual_quality",
                   "video.audio_intelligibility"],
                  "promotion.checker.qab@1", "promotion.video.qab@1",
                  ["technical", "content", "subtitle", "audio", "visual", "gui_layout",
                   "html_control", "review"],
                  subject="qab_report.json", expected_observation="required coverage",
                  pass_fail_rule="technical PASS; perceptual pending review"),
        workdir, run_id))
    tree = CapabilityTree("Provisional Promotion Studio QAB video", tuple(nodes))
    validate_required_obligations(tree, video_obligations(spec))
    return tree, compile_tree(tree)


def _checker_key(value: str) -> str:
    return str(value).split("@", 1)[0].split(".")[-1]


def validate_required_obligations(tree: CapabilityTree, plan: QualityPlan) -> None:
    represented = set()
    obligations = {item.id: item for item in plan.obligations}
    for node in tree.nodes:
        if node.capability_ref == "promotion.video.qab@1":
            # The acceptance aggregator names the obligations but cannot itself
            # provide the evidence-producing/checking capability.
            continue
        contract = node.config.get("leaf_contract", {})
        if not isinstance(contract, Mapping):
            continue
        if contract.get("task_kind") not in ("TEST", "INSPECTION"):
            continue
        checker = _checker_key(contract.get("checker_ref", ""))
        for oid in contract.get("acceptance", ()):
            obligation = obligations.get(str(oid))
            if obligation is not None and _checker_key(obligation.checker) == checker:
                represented.add(str(oid))
    missing = [oid for oid in plan.required_ids if oid not in represented]
    if missing:
        raise ValueError("required quality obligations missing from tree: " + ",".join(missing))


def exec_spec(request: BlockExecutionRequest) -> BlockExecutionResult:
    started = time.perf_counter(); cfg = _config(request)
    workdir = Path(cfg["workdir"]); spec = ensure_spec(workdir)
    manifest = {"spec": str(workdir / "video_task_spec.json"),
                "spec_sha256": sha256(workdir / "video_task_spec.json"),
                "status": spec["status"]}
    write_json(workdir / "trace" / "spec_manifest.json", manifest)
    return _result(request, manifest, started=request.created_at, clock=started)


def exec_gui(request: BlockExecutionRequest) -> BlockExecutionResult:
    started = time.perf_counter(); cfg = _config(request)
    workdir = Path(cfg["workdir"])
    gui = capture_gui(workdir, cfg["run_id"])
    return _result(request, {"gui": gui, "observations": gui["observations_path"],
                             "observations_sha256": gui["observations_sha256"]},
                   started=request.created_at, clock=started)


def exec_design(request: BlockExecutionRequest) -> BlockExecutionResult:
    started = time.perf_counter(); cfg = _config(request); deps = _deps(request)
    workdir = Path(cfg["workdir"])
    manifest = design_slides(workdir, deps["gui"]["gui"])
    return _result(request, manifest, started=request.created_at, clock=started)


def exec_gui_layout(request: BlockExecutionRequest) -> BlockExecutionResult:
    started = time.perf_counter(); cfg = _config(request); deps = _deps(request)
    workdir = Path(cfg["workdir"])
    observations = Path(deps["gui"]["observations"])
    value = check_gui(workdir, observations)
    return _result(request, value, started=request.created_at, clock=started)


def exec_script(request: BlockExecutionRequest) -> BlockExecutionResult:
    started = time.perf_counter(); cfg = _config(request)
    workdir = Path(cfg["workdir"])
    scenes = [{"scene": scene_id, "text": text} for scene_id, text in VIDEO_SCENES]
    write_json(workdir / "trace" / "scenes.json", {"scenes": scenes})
    write_json(workdir / "trace" / "narration_text.json", {
        "scenes": scenes, "language": "zh-CN",
        "design_baseline": "dark navy/teal provisional",
    })
    return _result(request, {"scenes": scenes, "scene_count": len(scenes)},
                   started=request.created_at, clock=started)


def exec_tts(request: BlockExecutionRequest) -> BlockExecutionResult:
    started = time.perf_counter(); cfg = _config(request); deps = _deps(request)
    workdir = Path(cfg["workdir"])
    scenes = deps["script"]["scenes"]
    texts = [item["text"] for item in scenes]
    tts = synthesize_narration(workdir, texts)
    scene_seconds = []
    for item in tts["parts"]:
        minimum = 5.0 if "录屏" in item["text"] else 3.5
        scene_seconds.append(max(minimum, float(item["duration"]) + 0.6))
    if sum(scene_seconds) < 30:
        scene_seconds = [value * (30.0 / sum(scene_seconds)) for value in scene_seconds]
    parts = [(Path(item["path"]), seconds)
             for item, seconds in zip(tts["parts"], scene_seconds)]
    narration = workdir / "evidence" / "audio" / "narration.wav"
    audio = concat_wavs(parts, narration)
    timeline = []
    cursor = 0.0
    for scene, seconds in zip(scenes, scene_seconds):
        timeline.append({"scene": scene["scene"], "start": round(cursor, 3),
                         "end": round(cursor + seconds, 3),
                         "duration": round(seconds, 3)})
        cursor += seconds
    manifest = {"narration": str(narration), "narration_sha256": sha256(narration),
                "timeline": timeline, "duration": round(cursor, 3),
                "voice": tts["voice"], "paid_provider": False,
                "scene_audio": tts["parts"]}
    write_json(workdir / "trace" / "tts_manifest.json", manifest)
    return _result(request, manifest, started=request.created_at, clock=started)


def exec_captions(request: BlockExecutionRequest) -> BlockExecutionResult:
    started = time.perf_counter(); cfg = _config(request); deps = _deps(request)
    workdir = Path(cfg["workdir"])
    scenes = deps["script"]["scenes"]
    timeline = deps["tts"]["timeline"]
    values = []
    for scene in scenes:
        timing = next(item for item in timeline if item["scene"] == scene["scene"])
        values.append({"scene": scene["scene"], "text": scene["text"],
                       "start": timing["start"], "end": timing["end"]})
    captions = build_captions(workdir, values)
    return _result(request, captions, started=request.created_at, clock=started)


def exec_render(request: BlockExecutionRequest) -> BlockExecutionResult:
    started = time.perf_counter(); cfg = _config(request); deps = _deps(request)
    workdir = Path(cfg["workdir"]); spec = ensure_spec(workdir)
    render = render_draft(workdir, spec, deps["design"],
                          deps["tts"], deps["gui"]["gui"]["recording"])
    return _result(request, render, started=request.created_at, clock=started)


def exec_mux(request: BlockExecutionRequest) -> BlockExecutionResult:
    started = time.perf_counter(); cfg = _config(request); deps = _deps(request)
    workdir = Path(cfg["workdir"])
    result = mux_final(workdir, Path(deps["render"]["draft"]),
                       Path(deps["tts"]["narration"]),
                       Path(deps["captions"]["srt"]),
                       workdir / "out" / "final.mp4")
    result["srt_sha256"] = deps["captions"]["srt_sha256"]
    result["narration_sha256"] = deps["tts"]["narration_sha256"]
    return _result(request, result, started=request.created_at, clock=started)


def exec_technical(request: BlockExecutionRequest) -> BlockExecutionResult:
    started = time.perf_counter(); cfg = _config(request); deps = _deps(request)
    workdir = Path(cfg["workdir"]); spec = ensure_spec(workdir)
    value = check_technical(workdir, Path(deps["mux"]["final"]), spec)
    return _result(request, value, started=request.created_at, clock=started)


def exec_content(request: BlockExecutionRequest) -> BlockExecutionResult:
    started = time.perf_counter(); cfg = _config(request); deps = _deps(request)
    workdir = Path(cfg["workdir"])
    value = check_content(workdir, Path(deps["mux"]["final"]),
                          Path(deps["render"]["shot_manifest"]),
                          deps["render"]["design"] if "design" in deps["render"] else
                          read_json(workdir / "evidence" / "design" / "design_manifest.json"))
    return _result(request, value, started=request.created_at, clock=started)


def exec_subtitle(request: BlockExecutionRequest) -> BlockExecutionResult:
    started = time.perf_counter(); cfg = _config(request); deps = _deps(request)
    workdir = Path(cfg["workdir"])
    value = check_subtitles(workdir, Path(deps["mux"]["final"]), Path(deps["captions"]["srt"]))
    return _result(request, value, started=request.created_at, clock=started)


def exec_audio(request: BlockExecutionRequest) -> BlockExecutionResult:
    started = time.perf_counter(); cfg = _config(request); deps = _deps(request)
    workdir = Path(cfg["workdir"]); spec = ensure_spec(workdir)
    value = check_audio(workdir, Path(deps["tts"]["narration"]), spec)
    return _result(request, value, started=request.created_at, clock=started)


def exec_visual(request: BlockExecutionRequest) -> BlockExecutionResult:
    started = time.perf_counter(); cfg = _config(request); deps = _deps(request)
    workdir = Path(cfg["workdir"])
    value = check_visual(workdir, Path(deps["mux"]["final"]))
    return _result(request, value, started=request.created_at, clock=started)


def exec_html(request: BlockExecutionRequest) -> BlockExecutionResult:
    started = time.perf_counter(); cfg = _config(request); deps = _deps(request)
    workdir = Path(cfg["workdir"])
    value = check_html(workdir, Path(deps["design"]["storyboard"]))
    return _result(request, value, started=request.created_at, clock=started)


def exec_qab(request: BlockExecutionRequest) -> BlockExecutionResult:
    started = time.perf_counter(); cfg = _config(request); deps = _deps(request)
    workdir = Path(cfg["workdir"]); spec = ensure_spec(workdir)
    values = {key: value for key, value in deps.items()}
    acceptance = qab_acceptance(workdir, spec, values)
    return _result(request, acceptance, started=request.created_at, clock=started)


def exec_review(request: BlockExecutionRequest) -> BlockExecutionResult:
    started = time.perf_counter(); cfg = _config(request); deps = _deps(request)
    workdir = Path(cfg["workdir"])
    contact = deps["visual"].get("object_versions", {}).get("contact_sheet.png", "")
    narration = deps["audio"].get("object_versions", {}).get("narration.wav", "")
    value = {"status": "PENDING_REVIEW",
             "obligations": ["video.visual_quality", "video.audio_intelligibility"],
             "object_versions": {"contact_sheet.png": contact, "narration.wav": narration},
             "checker_versions": {"review@1": "1"},
             "evidence_refs": ["evidence/results/review_pending.json"],
             "notes": "human visual and listening review not performed"}
    write_json(workdir / "evidence" / "results" / "review_pending.json", value)
    return _result(request, value, started=request.created_at, clock=started)


EXECUTORS: dict[str, Callable[[BlockExecutionRequest], BlockExecutionResult]] = {
    "promotion.video.spec@1": exec_spec,
    "promotion.video.gui@1": exec_gui,
    "promotion.video.design@1": exec_design,
    "promotion.video.gui-check@1": exec_gui_layout,
    "promotion.video.script@1": exec_script,
    "promotion.video.tts@1": exec_tts,
    "promotion.video.captions@1": exec_captions,
    "promotion.video.render@1": exec_render,
    "promotion.video.mux@1": exec_mux,
    "promotion.video.technical@1": exec_technical,
    "promotion.video.content@1": exec_content,
    "promotion.video.subtitle@1": exec_subtitle,
    "promotion.video.audio@1": exec_audio,
    "promotion.video.visual@1": exec_visual,
    "promotion.video.review@1": exec_review,
    "promotion.video.html@1": exec_html,
    "promotion.video.qab@1": exec_qab,
}


def run_video_tree(tree: CapabilityTree, dag: Any, workdir: Path, run_id: str) -> dict:
    from cgkn.execution.contracts import utc_now
    results: dict[str, BlockExecutionResult] = {}
    trace = []
    for node_id in dag.topological_order():
        node = dag.by_id[node_id]
        contract = dict(node.config["leaf_contract"])
        dependencies = {dep: dict(results[dep].outputs) for dep in node.depends_on}
        request = BlockExecutionRequest(
            project_id="promotion-qab", run_id=run_id,
            attempt_id="attempt-0001", node_id=node_id,
            component_ref=node.capability_ref,
            executor_ref=node.config["executor_ref"],
            task_context=TaskContext(
                node_goal=contract["leaf_goal"], node_config=node.config,
                dependency_results=dependencies,
                acceptance=tuple(contract.get("acceptance", ())),
            ),
            input_values={"workdir": str(workdir)}, timeout_seconds=600,
        )
        started = utc_now()
        try:
            result = EXECUTORS[node.capability_ref](request)
        except Exception as exc:
            result = BlockExecutionResult(
                project_id=request.project_id, run_id=request.run_id,
                attempt_id=request.attempt_id, node_id=node_id,
                executor_ref=request.executor_ref, status=BlockStatus.FAILED,
                outputs={}, started_at=started, ended_at=utc_now(),
                error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,
                                     "node failed", {"error": repr(exc)}),
            )
        results[node_id] = result
        trace.append({"node_id": node_id, "capability_ref": node.capability_ref,
                      "executor_ref": node.config["executor_ref"],
                      "dependencies": list(node.depends_on),
                      "status": result.status.value,
                      "outputs": dict(result.outputs),
                      "error": result.error.as_dict() if result.error else None})
        write_json(workdir / "trace" / "execution.json",
                   {"run_id": run_id, "tree": tree.as_dict(),
                    "dag": dag.as_dict(), "nodes": trace})
        if result.status is not BlockStatus.SUCCEEDED:
            raise RuntimeError("node failed: %s: %s" % (node_id, result.error))
    return {"results": {key: value.outputs for key, value in results.items()},
            "trace": trace}


def run_negative_controls(workdir: Path, spec: dict, results: Mapping[str, Mapping[str, Any]]) -> dict:
    import shutil
    neg = workdir / "negative"
    if neg.exists():
        shutil.rmtree(neg)
    neg.mkdir(parents=True, exist_ok=True)
    final = Path(results["mux"]["final"])
    narration = Path(results["tts"]["narration"])
    draft = Path(results["render"]["draft"])
    srt = Path(results["captions"]["srt"])
    shot_manifest = Path(results["render"]["shot_manifest"])
    design = read_json(workdir / "evidence" / "design" / "design_manifest.json")
    controls = []

    def add(name: str, mutation: str, injected: bool, expected: str,
            value: Mapping[str, Any]) -> None:
        controls.append({"name": name, "mutation": mutation, "injected": injected,
                         "expected": expected, "actual_status": value.get("status"),
                         "actual": dict(value),
                         "passed": injected and value.get("status") in (
                             "FAIL", "ERROR")})

    trim = neg / "trim.mp4"
    run([str(FFMPEG), "-y", "-i", str(final), "-t", "8", "-c", "copy", str(trim)])
    add("duration_wrong", "trim to 8 seconds", sha256(trim) != sha256(final),
        "FAIL", check_technical(workdir, trim, spec))

    noaudio = neg / "noaudio.mp4"
    run([str(FFMPEG), "-y", "-i", str(final), "-an", "-c:v", "copy", str(noaudio)])
    add("missing_required_audio", "strip audio stream", sha256(noaudio) != sha256(final),
        "FAIL", check_technical(workdir, noaudio, spec))

    silence = neg / "silence.mp4"
    duration = duration_of(final)
    run([str(FFMPEG), "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-i", str(final), "-t", f"{duration:.3f}", "-map", "0:a", "-map", "1:v",
         "-c:v", "copy", "-c:a", "aac", "-shortest", str(silence)])
    add("silent_narration", "replace narration with anullsrc", sha256(silence) != sha256(final),
        "FAIL", check_audio(workdir, narration, spec, audio_path=silence))

    corrupt = neg / "corrupt.mp4"
    raw = final.read_bytes()
    corrupt.write_bytes(raw[:max(1024, len(raw) // 3)])
    add("corrupt_midstream", "truncate to one third", sha256(corrupt) != sha256(final),
        "FAIL/ERROR", check_technical(workdir, corrupt, spec))

    black = neg / "black.mp4"
    run([str(FFMPEG), "-y", "-f", "lavfi", "-i", "color=c=black:s=1920x1080:d=12:r=30",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(black)])
    add("no_real_content", "replace with black video", sha256(black) != sha256(final),
        "FAIL", check_content(workdir, black, shot_manifest, design))

    nosubs = neg / "nosubs.mp4"
    run([str(FFMPEG), "-y", "-i", str(draft), "-i", str(narration),
         "-c:v", "copy", "-c:a", "aac", "-shortest", str(nosubs)])
    add("missing_subtitles", "mux without subtitles", sha256(nosubs) != sha256(final),
        "FAIL", check_subtitles(workdir, nosubs, srt))

    add("checker_missing", "point ffprobe at a missing executable", True,
        "ERROR", check_technical(workdir, final, spec,
                                 ffprobe_bin=neg / "missing-ffprobe.exe"))

    bad_html = neg / "bad_storyboard.html"
    bad_html.write_text("<html><body>no required text</body></html>", encoding="utf-8")
    add("html_text_missing", "remove required storyboard text", True,
        "FAIL", check_html(workdir, bad_html))

    bad_gui = neg / "bad_gui_observations.json"
    gui = read_json(Path(results["gui"]["observations"]))
    gui["no_page_errors"] = False
    write_json(bad_gui, gui)
    add("gui_page_error", "inject page error in observation", True,
        "FAIL", check_gui(workdir, bad_gui))

    payload = {"controls": controls,
               "tree_edit": tree_edit_negative(workdir, spec, "tree-edit"),
               "all_expected": all(item["passed"] for item in controls)}
    payload["all_expected"] = payload["all_expected"] and payload["tree_edit"]["passed"]
    write_json(workdir / "negative" / "negative_controls.json", payload)
    return payload


def run_incremental(workdir: Path, spec: dict, results: Mapping[str, Mapping[str, Any]]) -> dict:
    import shutil
    inc = workdir / "incremental"
    if inc.exists():
        shutil.rmtree(inc)
    inc.mkdir(parents=True, exist_ok=True)
    old_srt = Path(results["captions"]["srt"])
    text = old_srt.read_text(encoding="utf-8")
    new_srt = inc / "demo_incremental.srt"
    new_text = text.replace("Promotion Studio 是一个本地优先的内容审批与发布工作台。",
                            "Promotion Studio 是一个本地优先的工作台。", 1)
    if new_text == text:
        new_text = text.replace("真实界面", "真实界面（局部修订）", 1)
    if new_text == text:
        raise RuntimeError("incremental subtitle mutation did not apply")
    new_srt.write_text(new_text, encoding="utf-8")
    new_final = inc / "final_incremental.mp4"
    muxed = mux_final(workdir, Path(results["render"]["draft"]),
                      Path(results["tts"]["narration"]), new_srt, new_final)
    technical = check_technical(workdir, new_final, spec)
    content = check_content(workdir, new_final,
                            Path(results["render"]["shot_manifest"]),
                            read_json(workdir / "evidence" / "design" / "design_manifest.json"))
    subtitle = check_subtitles(workdir, new_final, new_srt)
    # Audio and GUI/HTML evidence are reused: their subjects are unchanged.
    reused_results = {
        "technical": technical, "content": content, "subtitle": subtitle,
        "audio": results["audio"], "visual": results["visual"],
        "gui_layout": results["gui_layout"], "html_control": results["html_control"],
    }
    reuse_acceptance_path = workdir / "trace" / "goal_acceptance.json"
    reuse_report_path = workdir / "trace" / "qab_report.json"
    initial_acceptance = reuse_acceptance_path.read_bytes() if reuse_acceptance_path.exists() else b""
    initial_report = reuse_report_path.read_bytes() if reuse_report_path.exists() else b""
    acceptance = qab_acceptance(workdir, spec, reused_results)
    if initial_acceptance:
        (inc / "goal_acceptance.json").write_bytes(reuse_acceptance_path.read_bytes())
        reuse_acceptance_path.write_bytes(initial_acceptance)
    if initial_report:
        (inc / "qab_report.json").write_bytes(reuse_report_path.read_bytes())
        reuse_report_path.write_bytes(initial_report)
    payload = {
        "old_srt_sha256": sha256(old_srt), "new_srt_sha256": sha256(new_srt),
        "old_final_sha256": results["mux"]["final_sha256"],
        "new_final_sha256": muxed["final_sha256"],
        "executed": ["mux", "technical", "content", "subtitle", "qab"],
        "reused": ["spec", "gui", "design", "gui_layout", "html_control",
                   "script", "tts", "audio", "visual"],
        "technical": technical, "content": content, "subtitle": subtitle,
        "acceptance": acceptance,
        "object_versions": {"old_final.mp4": results["mux"]["final_sha256"],
                            "new_final.mp4": muxed["final_sha256"]},
    }
    write_json(inc / "incremental.json", payload)
    return payload


def variant_case(workdir: Path, spec: dict, results: Mapping[str, Mapping[str, Any]]) -> dict:
    variant_dir = workdir / "variant"
    variant_dir.mkdir(parents=True, exist_ok=True)
    source = Path(results["mux"]["final"])
    variant = variant_dir / "boundary_1280x720_10s.mp4"
    run([str(FFMPEG), "-y", "-i", str(source), "-t", "10",
         "-vf", "scale=1280:720", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "22", "-c:a", "aac", "-b:a", "128k", "-shortest", str(variant)])
    variant_spec = json.loads(json.dumps(spec))
    variant_spec["duration"] = {"min_seconds": 8.0, "max_seconds": 12.0,
                                "target_seconds": 10.0, "tolerance_seconds": 2.0}
    variant_spec["resolution"] = {"width": 1280, "height": 720}
    check = check_technical(workdir, variant, variant_spec)
    payload = {"name": "different_material_size_and_boundary",
               "source": "trimmed 1280x720 10s equivalent",
               "expected": "PASS under the variant spec, not the original 1920x1080/55s spec",
               "actual": check, "passed": check.get("status") == "PASS"}
    write_json(workdir / "trace" / "variant_case.json", payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Run the QAB video tree")
    parser.add_argument("--workdir", default=r"C:\Users\sunom\VeriArbor-QAB-Video-20261107")
    parser.add_argument("--run-id", default="qab-run-01")
    parser.add_argument("--skip-negative", action="store_true")
    parser.add_argument("--skip-incremental", action="store_true")
    args = parser.parse_args(argv)
    workdir = Path(args.workdir).resolve()
    spec = ensure_spec(workdir)
    plan = video_obligations(spec)
    tree, dag = build_video_tree(workdir, spec, args.run_id)
    validate_required_obligations(tree, plan)
    write_json(workdir / "trace" / "tree.json", tree.as_dict())
    write_json(workdir / "trace" / "dag.json", dag.as_dict())
    run = run_video_tree(tree, dag, workdir, args.run_id)
    print(json.dumps({"status": "TREE_RUN_COMPLETE", "nodes": len(run["results"]),
                      "order": list(dag.topological_order())}, ensure_ascii=False))
    results_initial = workdir / "evidence" / "results_initial"
    frames_initial = workdir / "evidence" / "frames_initial"
    if results_initial.exists():
        shutil.rmtree(results_initial)
    shutil.copytree(workdir / "evidence" / "results", results_initial)
    if (workdir / "evidence" / "frames").exists():
        if frames_initial.exists():
            shutil.rmtree(frames_initial)
        shutil.copytree(workdir / "evidence" / "frames", frames_initial)
    if not args.skip_negative:
        negative = run_negative_controls(workdir, spec, run["results"])
        print(json.dumps({"negative_controls": negative["all_expected"]}, ensure_ascii=False))
    if not args.skip_incremental:
        incremental = run_incremental(workdir, spec, run["results"])
        print(json.dumps({"incremental": incremental["acceptance"]["status"]}, ensure_ascii=False))
    variant = variant_case(workdir, spec, run["results"])
    print(json.dumps({"variant_case": variant["passed"]}, ensure_ascii=False))
    # Negative/incremental measurements are retained in their own JSON; restore
    # the initial good evidence files so the delivery directory is unambiguous.
    shutil.copytree(results_initial, workdir / "evidence" / "results", dirs_exist_ok=True)
    if frames_initial.exists():
        shutil.copytree(frames_initial, workdir / "evidence" / "frames", dirs_exist_ok=True)
    print(json.dumps({"acceptance": read_json(workdir / "trace" / "goal_acceptance.json")["status"],
                      "final": str(workdir / "out" / "final.mp4")}, ensure_ascii=False))
    return 0


def tree_edit_negative(workdir: Path, spec: dict, run_id: str) -> dict:
    tree, _ = build_video_tree(workdir, spec, run_id + "-edit")
    plan = video_obligations(spec)
    known = {node.capability_ref for node in tree.nodes if node.capability_ref}
    tests = []

    def evaluate(name, edits, expected_fragment):
        rejected = False
        detail = ""
        try:
            edited = apply_tree_edits(tree, edits, known_capabilities=known)
            validate_required_obligations(edited, plan)
            detail = "edited tree unexpectedly passed the required-obligation gate"
        except Exception as exc:
            rejected = True
            detail = str(exc)
        result = {"name": name, "injected": True,
                  "expected": "reject missing " + expected_fragment,
                  "actual": detail,
                  "passed": rejected and expected_fragment in detail}
        tests.append(result)

    evaluate("delete_required_quality_node", (
        TreeEdit("edit-remove-dependency", "remove_dependency", "qab",
                 {"dependency": "subtitle"},
                 {"reason": "negative control: remove required subtitle check"}),
        TreeEdit("edit-remove-subtitle", "remove_node", "subtitle", {},
                 {"reason": "negative control: remove required subtitle check"}),
    ), "video.subtitles_burned")

    subtitle = tree.by_id["subtitle"]
    config = dict(subtitle.config)
    contract = dict(config["leaf_contract"])
    contract["acceptance"] = ["video.duration"]
    config["leaf_contract"] = contract
    evaluate("weaken_required_quality_contract", (
        TreeEdit("edit-weaken-subtitle", "update_config", "subtitle",
                 {"config": config},
                 {"reason": "negative control: remove required acceptance"}),
    ), "video.subtitles_burned")

    payload = {"tests": tests, "passed": all(item["passed"] for item in tests)}
    write_json(workdir / "negative" / "tree_edit_negative.json", payload)
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
