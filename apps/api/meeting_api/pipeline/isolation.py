"""把一次模型推理关进独立子进程，防止 C 扩展长时间独占 GIL 饿死事件循环。

起因：sherpa-onnx v1.13.6 的 pybind11 绑定（offline-speaker-diarization.cc）里
`OfflineSpeakerDiarization.process` 没有 `py::gil_scoped_release`，一段 87 分钟
录音要算约 12 分钟，全程持有 GIL——同进程的 uvicorn 事件循环一个字节码都执行
不了，`/healthz` 与所有只读接口一起超时。

修复要点在父进程这边：等结果用 `Connection.poll()`，它在等待时释放 GIL，
worker 线程算多久都不影响 HTTP。副作用是子进程退出即归还全部模型内存。

本模块只依赖标准库，pipeline 各后端可以在模块顶层 import，不会顺带把模型
运行时拖进来。
"""

from __future__ import annotations

import logging
import multiprocessing
import traceback
from collections.abc import Callable
from multiprocessing.connection import Connection

logger = logging.getLogger(__name__)

# 终止子进程后回收僵尸的等待上限：正常情况下瞬间返回。
_JOIN_TIMEOUT_SECONDS = 10.0


class IsolatedCallError(RuntimeError):
    """子进程没回传结果就结束了（崩溃、非零退出，或超时被终止）。"""


def _describe(target: Callable[..., object]) -> str:
    return getattr(target, "__qualname__", None) or repr(target)


def _send_error(conn: Connection, exc: BaseException, formatted: str) -> None:
    """把异常回传父进程；异常对象本身 pickle 不了就退化成同文案的 RuntimeError。"""
    try:
        conn.send(("error", exc, formatted))
    except Exception:
        conn.send(("error", RuntimeError(f"{type(exc).__name__}: {exc}"), formatted))


def _child_main(conn: Connection, target: Callable[..., object], args: tuple) -> None:
    """子进程入口：执行 target(*args)，把返回值或异常经管道交回父进程。"""
    try:
        try:
            result = target(*args)
        # 连 SystemExit / KeyboardInterrupt 也接住：子进程里静默退出等于父进程
        # 只能看到一个没头没尾的 EOF，什么都查不出来。
        except BaseException as exc:
            _send_error(conn, exc, traceback.format_exc())
            return
        try:
            conn.send(("ok", result))
        except Exception as exc:
            # 结果 pickle 不回去也算失败：别让父进程一路等到 EOF 才发现。
            _send_error(conn, exc, traceback.format_exc())
    finally:
        conn.close()


def run_isolated[T](
    target: Callable[..., T], /, *args: object, timeout: float | None = None
) -> T:
    """在 multiprocessing **spawn** 子进程里执行 target(*args)，把返回值带回来。

    target 必须是模块级、可 pickle 的可调用对象（spawn 子进程要重新 import 它
    所在的模块才能取到），args 同样必须可 pickle。

    一律用 spawn：macOS 主进程里已经有 onnxruntime / mlx 起的线程，fork 出来的
    子进程带着半截锁状态随时会死；Linux CI 也统一走 spawn，行为一致。

    子进程异常原样抛回调用方（traceback 先记进日志）；子进程没回传结果就退出，
    或超过 timeout 秒还没结果，抛 IsolatedCallError。
    """
    ctx = multiprocessing.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_child_main, args=(sender, target, args), daemon=True)
    process.start()
    # 父进程必须放掉写端，否则子进程死了也等不到 EOF。
    sender.close()
    try:
        # poll() 等待时释放 GIL——这一步才是「事件循环不再被饿死」的关键。
        if not receiver.poll(timeout):
            process.terminate()
            process.join(_JOIN_TIMEOUT_SECONDS)
            raise IsolatedCallError(
                f"隔离子进程执行 {_describe(target)} 超过 {timeout} 秒未返回，已终止"
            )
        try:
            payload = receiver.recv()
        except (EOFError, OSError):
            payload = None
        if payload is None:
            process.join(_JOIN_TIMEOUT_SECONDS)
            raise IsolatedCallError(
                f"隔离子进程执行 {_describe(target)} 时异常退出"
                f"（exitcode={process.exitcode}），没有回传结果"
            )
        if payload[0] == "ok":
            return payload[1]
        _, exc, formatted = payload
        logger.error("隔离子进程执行 %s 失败：\n%s", _describe(target), formatted)
        raise exc
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
        process.join(_JOIN_TIMEOUT_SECONDS)
