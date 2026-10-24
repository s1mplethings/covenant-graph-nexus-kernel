from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess
import textwrap
from dataclasses import asdict

from .contracts import CampaignBrief, MediaAsset, PromotionVideoPlan, canonical_hash


ASSET_POLICY_VERSION = "promotion-assets-v1.0"
VIDEO_POLICY_VERSION = "promotion-video-ffmpeg-v1.0"


def file_hash(path: pathlib.Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class DeterministicAssetRenderer:
    def __init__(self, root: pathlib.Path | str) -> None:
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def render_card(self, brief: CampaignBrief, claims: tuple[str, ...], evidence_ids: tuple[str, ...], *, width: int = 1200, height: int = 675) -> MediaAsset:
        if not claims:
            raise ValueError("card requires grounded claims")
        from PIL import Image, ImageDraw, ImageFont
        target = self.root / f"{brief.campaign_id}-card-{width}x{height}.png"
        canvas = Image.new("RGB", (width, height), "#07111f"); draw = ImageDraw.Draw(canvas)
        margin = max(30, width // 32); draw.rounded_rectangle((margin, margin, width - margin, height - margin), radius=28, fill="#10243e", outline="#4ba3ff", width=3)
        font_path = pathlib.Path("C:/Windows/Fonts/arial.ttf")
        bold_path = pathlib.Path("C:/Windows/Fonts/arialbd.ttf")
        def font(size: int, *, bold: bool = False):
            candidate = bold_path if bold else font_path
            return ImageFont.truetype(str(candidate), size) if candidate.is_file() else ImageFont.load_default()
        x = margin + 44; y = margin + 38
        draw.text((x, y), "CGKN  /  VERIFIED PROJECT EVIDENCE", fill="#63b3ff", font=font(max(18, width // 44)))
        y += max(48, height // 10)
        for line in textwrap.wrap(brief.core_message[:120], width=max(24, width // 24))[:2]:
            draw.text((x, y), line, fill="white", font=font(max(28, width // 28), bold=True)); y += max(42, height // 12)
        y += 12
        for claim in claims[:3]:
            for index, line in enumerate(textwrap.wrap(claim[:140], width=max(28, width // 20))[:2]):
                draw.text((x + (18 if index else 0), y), ("• " if index == 0 else "") + line, fill="#d8e5ff", font=font(max(18, width // 42))); y += max(30, height // 18)
            y += 6
        draw.text((x, height - margin - max(38, height // 16)), "Evidence-bound  •  local-first  •  approval required", fill="#8ca3bd", font=font(max(16, width // 55)))
        canvas.save(target, format="PNG", optimize=False)
        config_hash = canonical_hash({"policy": ASSET_POLICY_VERSION, "width": width, "height": height, "claims": claims})
        return MediaAsset(f"asset-{brief.campaign_id}-card-{width}x{height}", brief.campaign_id, "PROJECT_CARD", str(target), "image/png", file_hash(target), evidence_ids, "cgkn.deterministic.png@1", config_hash, width, height)

    def render_video(self, plan: PromotionVideoPlan, evidence_ids: tuple[str, ...]) -> MediaAsset:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            raise RuntimeError("FFMPEG_UNAVAILABLE")
        target = self.root / f"{plan.campaign_id}-{plan.width}x{plan.height}.mp4"
        def safe(value: str) -> str:
            return value.replace("\\", "").replace("'", "’").replace(":", "-").replace("%", "percent")[:90]
        safe_title = safe(plan.title)
        safe_caption = safe(" • ".join(plan.captions[:2]))
        safe_cta = safe(plan.cta)
        font = "Arial"
        vf = (
            f"drawtext=font='{font}':text='{safe_title}':fontcolor=white:fontsize={max(28, plan.width // 18)}:"
            f"x=(w-text_w)/2:y=h*0.27,drawtext=font='{font}':text='{safe_caption}':fontcolor=0xd8e5ff:"
            f"fontsize={max(22, plan.width // 26)}:x=(w-text_w)/2:y=h*0.48,drawtext=font='{font}':text='{safe_cta}':fontcolor=0x63b3ff:"
            f"fontsize={max(22, plan.width // 26)}:x=(w-text_w)/2:y=h*0.68"
        )
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x07111f:s={plan.width}x{plan.height}:d={plan.duration_seconds}", "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={plan.duration_seconds}", "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(target)]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        if completed.returncode != 0 or not target.is_file():
            raise RuntimeError("FFMPEG_RENDER_FAILED: " + completed.stderr[-300:])
        probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_name,width,height,codec_type", "-of", "json", str(target)], capture_output=True, text=True, timeout=30, check=False)
        if probe.returncode != 0:
            raise RuntimeError("FFPROBE_FAILED")
        info = json.loads(probe.stdout)
        streams = info.get("streams", [])
        video = next((item for item in streams if item.get("codec_type") == "video"), None)
        audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
        if not video or not audio or video.get("codec_name") != "h264" or int(video.get("width", 0)) != plan.width or int(video.get("height", 0)) != plan.height:
            raise RuntimeError("VIDEO_ACCEPTANCE_FAILED")
        duration = float(info.get("format", {}).get("duration", 0))
        config_hash = canonical_hash({"policy": VIDEO_POLICY_VERSION, "plan": asdict(plan), "streams": streams})
        return MediaAsset(f"asset-{plan.campaign_id}-video-{plan.width}x{plan.height}", plan.campaign_id, "PROMOTION_VIDEO", str(target), "video/mp4", file_hash(target), evidence_ids, "ffmpeg.local@1", config_hash, plan.width, plan.height, duration)

