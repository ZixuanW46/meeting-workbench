"""Plaud 通道的错误分类；路由据此映射 HTTP 状态码。"""

from __future__ import annotations

# 用户可见文案统一在这里，路由与 /api/plaud/status 共用。
PLAUD_NOT_INSTALLED_MESSAGE = "Plaud MCP 未安装（npm i -g @plaud-ai/mcp）"
PLAUD_NOT_LOGGED_IN_MESSAGE = "Plaud 未登录，请先登录"
PLAUD_TIMEOUT_MESSAGE = "Plaud 请求超时"


class PlaudError(RuntimeError):
    """上游 Plaud / MCP 异常，路由映射 502。"""


class PlaudAuthError(PlaudError):
    """未登录，路由映射 503。"""


class PlaudUnavailableError(PlaudError):
    """本机没装 MCP 命令，路由映射 503。"""


class PlaudTimeoutError(PlaudError):
    """工具调用或下载超时，路由映射 504。"""
