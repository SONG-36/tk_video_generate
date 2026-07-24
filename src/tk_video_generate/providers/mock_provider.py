from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from PIL import Image

from tk_video_generate.config import AppConfig
from tk_video_generate.models import VideoTask
from tk_video_generate.providers.base import ProviderError, VideoProvider


class MockVideoProvider(VideoProvider):
    name = "mock"

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def estimate_cost(self, task_count: int, duration_seconds: int) -> float:
        return round(task_count * duration_seconds * 0.01, 2)

    def generate(self, task: VideoTask, output_dir: Path) -> dict[str, object]:
        prompt = task.prompt.lower()
        request_path = output_dir / "request.json"
        result_path = output_dir / "result.json"
        video_path = output_dir / "result.mp4"

        self._write_json(
            request_path,
            {
                "task_id": task.id,
                "batch_id": task.batch_id,
                "provider": self.name,
                "prompt": task.prompt,
                "duration_seconds": task.duration_seconds,
                "aspect_ratio": task.aspect_ratio,
                "image_path": task.image_path,
            },
        )

        if "[mock-fail]" in prompt:
            time.sleep(0.5)
            raise ProviderError("MOCK_FORCED_FAILURE", "Prompt requested a forced mock failure.")

        if "[mock-timeout]" in prompt:
            time.sleep(2.0)
            raise ProviderError("MOCK_TIMEOUT", "Prompt requested a simulated mock timeout.")

        self._validate_image(Path(task.image_path))
        self._generate_video(Path(task.image_path), video_path, task.duration_seconds)
        probe = self._probe_video(video_path)

        result = {
            "task_id": task.id,
            "provider": self.name,
            "provider_task_id": f"mock-{task.id}",
            "status": "succeeded",
            "video_path": str(video_path),
            "duration_seconds": task.duration_seconds,
            "aspect_ratio": task.aspect_ratio,
            "ffprobe": probe,
        }
        self._write_json(result_path, result)
        return result

    def _validate_image(self, image_path: Path) -> None:
        try:
            with Image.open(image_path) as image:
                image.verify()
        except Exception as exc:
            raise ProviderError("INVALID_IMAGE", f"Invalid first-frame image: {exc}") from exc

    def _generate_video(self, image_path: Path, video_path: Path, duration_seconds: int) -> None:
        video_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.config.ffmpeg_path,
            "-y",
            "-loop",
            "1",
            "-i",
            str(image_path),
            "-t",
            str(duration_seconds),
            "-r",
            "24",
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(video_path),
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise ProviderError(
                "FFMPEG_FAILED",
                f"FFmpeg failed with exit {completed.returncode}: {completed.stderr[-1000:]}",
            )

    def _probe_video(self, video_path: Path) -> dict[str, object]:
        cmd = [
            self.config.ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt,width,height",
            "-of",
            "json",
            str(video_path),
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise ProviderError(
                "FFPROBE_FAILED",
                f"FFprobe failed with exit {completed.returncode}: {completed.stderr[-1000:]}",
            )
        return json.loads(completed.stdout)

    def _write_json(self, path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
