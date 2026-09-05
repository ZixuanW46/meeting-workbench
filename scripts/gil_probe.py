"""GIL 探针：量一量 sherpa-onnx 切分各阶段有没有把 GIL 抱死（仅限放好模型的 macOS 真机）。

背景见 docs/DIARIZATION-GIL.md：生产机处理长录音到 DIARIZATION 步骤时，同进程的
uvicorn 事件循环被饿死，/healthz 也超时。本脚本把可疑的每一步放到后台线程跑，主线程
每 10 ms 醒一次记录「两次醒来之间的最大间隔」——间隔接近整步耗时，就说明这一步全程
持有 GIL；间隔只有几十毫秒，说明这一步会释放 GIL。

用法（在仓库根目录，不会改任何产品数据）：
    .venv/bin/python scripts/gil_probe.py data/meetings/<id>/raw/xxx.wav --seconds 120

只截取录音开头 --seconds 秒到临时文件，避免整场跑几分钟。
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def slice_wav(source: Path, seconds: float, target: Path) -> tuple[int, int]:
    with wave.open(str(source), "rb") as reader:
        params = reader.getparams()
        frames = reader.readframes(int(params.framerate * seconds))
    with wave.open(str(target), "wb") as writer:
        writer.setparams(params)
        writer.writeframes(frames)
    return params.framerate, params.nchannels


def build_models(model_dir: Path) -> tuple[Any, Any]:
    """与 SherpaOnnxDiarizationBackend.load() 相同的配置，直接建模型便于单独计时。"""
    import sherpa_onnx

    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(model_dir / "segmentation.onnx"), window_shift_ratio=0.1
            )
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(model_dir / "embedding.onnx")
        ),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=0.5),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not config.validate():
        raise SystemExit(f"sherpa-onnx 配置无效，请检查 {model_dir}/")
    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(model_dir / "embedding.onnx"))
    )
    return sherpa_onnx.OfflineSpeakerDiarization(config), extractor


def measure(label: str, fn: Callable[[], Any]) -> Any:
    """fn 在后台线程跑；主线程做 10 ms 探针，打印最大停顿。"""
    done = threading.Event()
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # 探针要把任何失败都带回主线程
            box["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=run, daemon=True)
    started = time.monotonic()
    last = started
    max_gap = 0.0
    ticks = 0
    thread.start()
    while not done.is_set():
        time.sleep(0.01)
        now = time.monotonic()
        max_gap = max(max_gap, now - last)
        last = now
        ticks += 1
    total = time.monotonic() - started
    verdict = "抱死 GIL" if max_gap > 0.5 else "会释放 GIL"
    print(
        f"[{label}] 总耗时 {total:.2f}s，探针醒来 {ticks} 次，"
        f"最大停顿 {max_gap:.2f}s → {verdict}",
        flush=True,
    )
    if "error" in box:
        raise box["error"]
    return box.get("result")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("wav", type=Path, help="16 kHz 单声道 WAV（会议 raw 音频）")
    parser.add_argument("--seconds", type=float, default=120.0, help="只取开头这么多秒")
    parser.add_argument(
        "--models-dir", type=Path, default=REPO_ROOT / "data" / "models", help="模型根目录"
    )
    parser.add_argument("--slice", type=Path, default=Path("/tmp/gil_probe_slice.wav"))
    args = parser.parse_args()
    if sys.platform != "darwin":
        print("真实后端仅支持 macOS；本脚本只在放好模型的真机上有意义。", file=sys.stderr)
        return 2

    import numpy as np
    import soundfile as sf

    rate, channels = slice_wav(args.wav, args.seconds, args.slice)
    print(f"切片 {args.seconds:.0f}s @ {rate} Hz，{channels} 声道 → {args.slice}", flush=True)

    model, extractor = measure(
        "加载模型", lambda: build_models(args.models_dir / "sherpa-onnx")
    )
    audio, sample_rate = measure(
        "soundfile 读整段", lambda: sf.read(args.slice, dtype="float32", always_2d=True)
    )
    samples = np.ascontiguousarray(audio[:, 0])
    if sample_rate != model.sample_rate:
        samples = measure(
            "np.interp 重采样",
            lambda: np.interp(
                np.linspace(
                    0,
                    len(samples),
                    round(len(samples) * model.sample_rate / sample_rate),
                    endpoint=False,
                ),
                np.arange(len(samples)),
                samples,
            ).astype("float32"),
        )

    result = measure("process()（无回调，产品代码现状）", lambda: model.process(samples))
    segments = [
        (float(item.start), float(item.end), int(item.speaker))
        for item in result.sort_by_start_time()
    ]
    print(f"  片段 {len(segments)} 个，簇 {len({s[2] for s in segments})} 个", flush=True)

    calls: list[float] = []

    def progress(processed: int, total: int) -> int:
        calls.append(time.monotonic())
        time.sleep(0)  # 让出 GIL
        return 0

    measure("process()（带进度回调 + sleep(0)）", lambda: model.process(samples, progress))
    if len(calls) > 1:
        gaps = [later - earlier for earlier, later in zip(calls, calls[1:], strict=False)]
        print(
            f"  回调 {len(calls)} 次，回调之间最大间隔 {max(gaps):.3f}s"
            "（回调只覆盖 embedding 阶段，segmentation 阶段仍无回调）",
            flush=True,
        )

    def embed_first_spans() -> int:
        computed = 0
        for start, end, _ in segments[:20]:
            piece = samples[int(start * sample_rate) : int(end * sample_rate)]
            if len(piece) < int(0.3 * sample_rate):
                continue
            stream = extractor.create_stream()
            stream.accept_waveform(sample_rate=sample_rate, waveform=piece)
            stream.input_finished()
            if extractor.is_ready(stream):
                extractor.compute(stream)
                computed += 1
        return computed

    computed = measure("SpeakerEmbeddingExtractor.compute() ×20", embed_first_spans)
    print(f"  提取声纹 {computed} 条", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
