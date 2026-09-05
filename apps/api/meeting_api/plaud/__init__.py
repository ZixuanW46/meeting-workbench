"""Plaud 云端录音导入：MCP stdio 客户端、网关与音频下载。

登录态由 Plaud 官方 MCP server 自己维护在 ~/.plaud，本模块只通过工具调用访问，
绝不读写那个文件，也不碰任何 token。
"""
