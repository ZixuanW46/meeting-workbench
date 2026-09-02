"""音频波形峰值：后端按 PCM WAV 算一次、落盘缓存，浏览器只拿一份小数组。

两小时 16kHz 音频解码后是上 GB 的浮点数据；确认页十几张卡各自解码一遍会把
浏览器压垮。这里用标准库 wave 分桶取绝对峰值，归一化到 0～1，最多 2000 桶。
非 PCM WAV（FLAC/OGG 等）不支持：调用方按「无波形」降级，试听照常。
"""

from __future__ import annotations

import json
import wave
from array import array
from pathlib import Path

from meeting_api.config import Settings
from meeting_api.storage import meeting_dir

PEAK_BUCKETS = 2000
_TYPECODES = {1: "b", 2: "h", 4: "i"}


class PeaksUnavailable(Exception):
    """音频不是可解析的 PCM WAV，或文件缺失。"""


def compute_peaks(audio_path: Path, buckets: int = PEAK_BUCKETS) -> tuple[float, list[float]]:
    try:
        with wave.open(str(audio_path), "rb") as reader:
            rate = reader.getframerate()
            channels = reader.getnchannels()
            width = reader.getsampwidth()
            frames = reader.getnframes()
            typecode = _TYPECODES.get(width)
            if typecode is None or rate <= 0 or frames <= 0:
                raise PeaksUnavailable(str(audio_path))
            full_scale = float(2 ** (8 * width - 1))
            bucket_count = min(buckets, frames)
            peaks: list[float] = []
            consumed = 0
            for index in range(bucket_count):
                # 桶边界按帧数均分；最后一桶吃掉余数。
                target = (
                    frames
                    if index == bucket_count - 1
                    else (frames * (index + 1)) // bucket_count
                )
                raw = reader.readframes(target - consumed)
                consumed = target
                samples = array(typecode)
                samples.frombytes(raw[: len(raw) - len(raw) % samples.itemsize])
                if len(samples) == 0:
                    peaks.append(0.0)
                    continue
                # 多声道交错存储：直接在交错流上取绝对峰值即可。
                peak = max(max(samples), -min(samples))
                peaks.append(min(1.0, peak / full_scale))
            del channels
            return frames / rate, peaks
    except (wave.Error, EOFError, OSError) as exc:
        raise PeaksUnavailable(str(audio_path)) from exc


def peaks_cache_path(settings: Settings, meeting_id: str) -> Path:
    return meeting_dir(settings, meeting_id) / "peaks.json"


def load_or_compute_peaks(
    settings: Settings, meeting_id: str, audio_path: Path | None
) -> dict[str, object]:
    """先读缓存；没有就从原始音频算并落盘。缓存在音频删除后仍可用。"""
    cache = peaks_cache_path(settings, meeting_id)
    if cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    if audio_path is None or not audio_path.is_file():
        raise PeaksUnavailable(meeting_id)
    duration, peaks = compute_peaks(audio_path)
    payload: dict[str, object] = {"duration": duration, "peaks": peaks}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return payload
