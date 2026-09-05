"""子进程隔离：证明 C 扩展长时间独占 GIL 时 API 仍然可用。

注意：spawn 子进程会重新 import 本模块来取回调，所以所有子进程入口都写成
模块级函数，模块顶层不做任何重活。tests/ 没有 __init__.py，测试之间不能互相
import，需要的 helper（_queue_meeting）在本文件内联复制。
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from meeting_api.pipeline.diarization import FakeDiarizationBackend, SpeakerSegment
from meeting_api.pipeline.isolation import IsolatedCallError, run_isolated
from meeting_api.worker import Worker


def _queue_meeting(client, title: str = "待处理会议", expected_speakers: int = 2) -> str:
    created = client.post(
        "/api/meetings",
        json={"title": title, "expected_speakers": expected_speakers},
    )
    assert created.status_code == 201
    meeting_id = created.json()["id"]
    uploaded = client.post(
        f"/api/meetings/{meeting_id}/upload",
        files={"file": ("meeting.wav", b"fake audio bytes", "audio/wav")},
    )
    assert uploaded.status_code == 200
    return meeting_id


# ---- 子进程入口（必须是模块级、可 pickle 的函数）----------------------------


def _double(value: int) -> int:
    return value * 2


def _boom() -> None:
    raise ValueError("坏了")


def _exit_hard() -> None:
    # 绕过所有清理直接退出：模拟 C 扩展把子进程搞崩
    os._exit(7)


def _sleep_long(seconds: float) -> None:
    time.sleep(seconds)


# 校准基准：先量一次固定规模的耗时，再线性放大到目标秒数。
_HOG_CALIBRATION_STEPS = 2_000_000
# 目标时长下限：低于这个数机器抖动就能盖过探针停顿，断言会变得不稳。
_HOG_MIN_SECONDS = 0.8


def _time_calibration_run() -> float:
    started = time.perf_counter()
    sum(range(_HOG_CALIBRATION_STEPS))
    return max(time.perf_counter() - started, 1e-6)


def _hog_steps_for(seconds: float) -> int:
    """按本机速度粗校准出「霸占 GIL 约 seconds 秒」需要的循环规模。"""
    # 取两次里更快的一次：别的线程抢 GIL 会把单次测量拉长，照着虚高的耗时
    # 缩规模，hog 就短得探不出停顿了。
    unit_seconds = min(_time_calibration_run(), _time_calibration_run())
    target_seconds = max(seconds, _HOG_MIN_SECONDS)
    return max(
        int(_HOG_CALIBRATION_STEPS * target_seconds / unit_seconds),
        _HOG_CALIBRATION_STEPS,
    )


def _hog_gil(seconds: float) -> int:
    """独占 GIL 至少 seconds 秒，模拟 sherpa-onnx 的 process()。

    关键是「单次 C 级长调用」：CPython 的 builtin_sum 对 int 走 C 循环快路径，
    整个循环里不检查 eval breaker，别的线程一个字节码都插不进来。
    用 Python 层 while 循环反而会定期让出 GIL，探不出问题。
    """
    return sum(range(_hog_steps_for(seconds)))


def _hog_then_segments(seconds: float) -> list[SpeakerSegment]:
    """子进程里先独占 GIL，再返回与 fake 切分一致的结果。"""
    _hog_gil(seconds)
    backend = FakeDiarizationBackend()
    backend.load()
    try:
        return backend.diarize(Path("unused.wav"), expected_speakers=2)
    finally:
        backend.unload()


class _GilHogDiarizationBackend:
    """切分后端替身：结构与 FakeDiarizationBackend 同构，但在子进程里霸占 GIL。"""

    name = "gil-hog-diarization"

    def __init__(self, seconds: float = 1.5) -> None:
        self.seconds = seconds
        self.entered = threading.Event()
        self._loaded = False

    def load(self) -> None:
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def diarize(
        self, audio_path: Path, expected_speakers: int | None = None
    ) -> list[SpeakerSegment]:
        if not self._loaded:
            raise RuntimeError("diarization 后端未加载（先 load()）")
        del audio_path, expected_speakers
        self.entered.set()
        return run_isolated(_hog_then_segments, self.seconds)


# ---- 用例 -------------------------------------------------------------------


def test_run_isolated_returns_result_and_propagates_exception():
    assert run_isolated(_double, 21) == 42

    with pytest.raises(ValueError, match="坏了"):
        run_isolated(_boom)


def test_run_isolated_reports_child_death():
    with pytest.raises(IsolatedCallError) as excinfo:
        run_isolated(_exit_hard)

    # 退出码要带进消息里，否则真机上根本看不出子进程是怎么没的。
    assert "7" in str(excinfo.value)


def test_run_isolated_times_out():
    started = time.perf_counter()

    with pytest.raises(IsolatedCallError):
        run_isolated(_sleep_long, 60.0, timeout=1.0)

    # 超时从等结果开始算；spawn 起进程约 1s，总时长仍必须远小于子进程的 60s。
    assert time.perf_counter() - started < 10.0


def test_gil_hog_really_blocks_other_threads():
    """先证明探针有意义：同进程跑 hog 时，主线程的 10ms 心跳会被明显拖住。"""
    hog = threading.Thread(target=_hog_gil, args=(1.5,), daemon=True)
    gaps: list[float] = []

    hog.start()
    last = time.perf_counter()
    while hog.is_alive():
        time.sleep(0.01)
        now = time.perf_counter()
        gaps.append(now - last)
        last = now
    hog.join()

    assert gaps
    print(
        f"\n[gil-probe] 校准规模 n={_hog_steps_for(1.5):,}，"
        f"同进程 hog 期间主线程最大停顿 {max(gaps):.3f}s"
    )
    assert max(gaps) >= 0.3


def test_healthz_and_readonly_api_stay_responsive_while_diarization_hogs_gil(client):
    """验收指标：切分独占 GIL 期间，/healthz 与只读接口都要秒回。"""
    meeting_id = _queue_meeting(client)
    hog = _GilHogDiarizationBackend()
    worker = Worker(
        session_factory=client.app.state.session_factory,
        settings=client.app.state.settings,
        diarization_backend=hog,
    )
    thread = threading.Thread(target=worker.process_next, daemon=True)

    thread.start()
    try:
        assert hog.entered.wait(5.0), "切分没有在 5s 内开工"
        started = time.perf_counter()
        health = client.get("/healthz")
        health_seconds = time.perf_counter() - started
        started = time.perf_counter()
        listing = client.get("/api/meetings")
        listing_seconds = time.perf_counter() - started
    finally:
        thread.join(timeout=60.0)

    print(
        f"\n[api-probe] /healthz {health_seconds:.3f}s，"
        f"/api/meetings {listing_seconds:.3f}s"
    )
    assert health.status_code == 200
    assert listing.status_code == 200
    assert health_seconds < 1.0
    assert listing_seconds < 1.0

    # 隔离不能改变结果：这一场照常走完到确认停点。
    detail = client.get(f"/api/meetings/{meeting_id}")
    assert detail.json()["state"] == "AWAITING_SPEAKER_REVIEW"
