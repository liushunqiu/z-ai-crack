"""urllib 单次代理工具: 每个请求独立走 SOCKS5 / HTTP 代理, 不 monkey-patch socket。

用法:
    from bridge.socks_urllib import make_opener
    opener = make_opener("socks5://127.0.0.1:33211")   # 或 http://...
    resp = opener.open(req, timeout=180)                # 等价 urllib.request.urlopen

为什么不用全局 `socket.socket = socks.socksocket`:
  全局替换会让所有账号共享同一个默认代理, 无法实现 per-account 不同出口 IP。
"""
from __future__ import annotations

import http.client
import urllib.request
import urllib.error
from typing import Optional
from urllib.parse import urlparse


def _parse_proxy(proxy: str) -> tuple[str, str, int, Optional[str], Optional[str]]:
    """返回 (scheme, host, port, user, password)。"""
    p = urlparse(proxy)
    scheme = (p.scheme or "").lower()
    host = p.hostname or ""
    port = p.port
    if not port:
        port = 1080 if scheme.startswith("socks") else 8080
    return scheme, host, port, p.username, p.password


def _make_socks5_connection(proxy_host: str, proxy_port: int,
                            proxy_user: Optional[str], proxy_pass: Optional[str]):
    """返回一个 factory 函数: (target_host, target_port, timeout) -> socksocket。"""
    import socks  # pysocks
    proxy_type = socks.SOCKS5

    def factory(host: str, port: int, timeout: float) -> "socks.socksocket":
        s = socks.socksocket()
        s.set_proxy(
            proxy_type, proxy_host, proxy_port,
            username=proxy_user, password=proxy_pass,
        )
        if timeout:
            s.settimeout(timeout)
        s.connect((host, port))
        return s

    return factory


class SOCKS5HTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection 子类: 通过 SOCKS5 建连, 替代默认 socket。"""

    def __init__(self, host, port=None, *, socks_factory, **kwargs):
        self._socks_factory = socks_factory
        super().__init__(host, port, **kwargs)

    def connect(self):
        sock = self._socks_factory(self.host, self.port or 443, self.timeout)
        # HTTPSConnection 的 _context 是 ssl.SSLContext, wrap_socket 走 SNI
        ssock = self._context.wrap_socket(sock, server_hostname=self.host)
        self.sock = ssock


class SOCKS5HTTPSHandler(urllib.request.HTTPSHandler):
    """注册到 opener 的 handler, 根据目标 host 返回 SOCKS5HTTPSConnection。"""

    def __init__(self, socks_factory):
        super().__init__()
        self._socks_factory = socks_factory

    def https_open(self, req):
        return self.do_open(
            lambda host, port=None, **kw: SOCKS5HTTPSConnection(
                host, port, socks_factory=self._socks_factory, **kw
            ),
            req,
        )


def make_opener(proxy: Optional[str]) -> urllib.request.OpenerDirector:
    """构造一个 urllib opener。proxy 为空时返回默认 opener (直连)。

    支持格式:
      - socks5://host:port (pysocks)
      - socks5h://host:port (同上, 远端 DNS 解析 — pysocks 默认行为)
      - http://host:port (urllib ProxyHandler)
      - https://host:port (urllib ProxyHandler)
    """
    if not proxy:
        return urllib.request.build_opener()

    scheme, host, port, user, pw = _parse_proxy(proxy)

    if scheme.startswith("socks"):
        factory = _make_socks5_connection(host, port, user, pw)
        return urllib.request.build_opener(SOCKS5HTTPSHandler(factory))

    if scheme in ("http", "https"):
        # urllib ProxyHandler 走 CONNECT 隧道 (HTTPS 目标)
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )

    raise ValueError(f"Unsupported proxy scheme: {scheme!r} (in {proxy!r})")
