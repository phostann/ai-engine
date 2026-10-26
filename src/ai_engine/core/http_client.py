import asyncio
import random
from typing import Any

import httpx


class ProductionHttpClient:
    """生产级异步 HTTP 客户端：连接池复用 + 非对称超时 + Full-Jitter 退避重试"""

    def __init__(
        self,
        *,
        base_url: str = "",
        headers: dict[str, str] | None = None,
        max_connections: int = 100,
        max_keepalive: int = 20,
        connect_timeout: float = 5.0,
        read_timeout: float = 60.0,
    ) -> None:
        # TODO 1: 配置 httpx.Limits, 设置最大连接数与最大保活连接数
        self._limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive,
            keepalive_expiry=30.0,
        )

        # TODO 2: 配置非对称超时 httpx.Timeout
        self._timeout = httpx.Timeout(
            connect=connect_timeout, read=read_timeout, write=10.0, pool=5.0
        )
        self._base_url = base_url
        self._headers = headers
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "ProductionHttpClient":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            limits=self._limits,
            timeout=self._timeout,
        )
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("请在 async with 上下文中使用此客户端！")
        return self._client

    async def request_with_jitter_retry(
        self, method: str, url: str, *, max_retries: int = 3, base_delay: float = 0.5, **kwargs: Any
    ) -> httpx.Response:
        """带 Full-Jitter 抖动的重试，避免并发请求在同一刻同时重试触发静群"""
        retryable_codes = {429, 500, 502, 503, 504}
        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                resp = await self.client.request(method, url, **kwargs)
                if resp.status_code not in retryable_codes:
                    resp.raise_for_status()
                    return resp

                last_error = httpx.HTTPStatusError(
                    f"可重试状态码：{resp.status_code}", request=resp.request, response=resp
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and (
                    exc.response.status_code not in retryable_codes
                ):
                    # 400 Bad Request 或 401 Unauthorized 绝对不进行盲目重试
                    raise
                last_error = exc

            if attempt == max_retries:
                break

            # TODO 3: 实现 Full-Jitter 退避公式
            # 计算上限：max_sleep = base_delay * (2 ** (attempt - 1))
            # 随机休眠：在 [0.05, max_sleep] 之间生成随机浮点数并 await asyncio.sleep
            max_sleep = base_delay * (2 ** (attempt - 1))
            sleep_time = random.uniform(0.05, max_sleep)
            await asyncio.sleep(sleep_time)

        assert last_error is not None
        raise last_error
