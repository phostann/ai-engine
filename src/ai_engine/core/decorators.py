import asyncio
import functools
import time
from collections.abc import Callable, Coroutine
from typing import Any, ParamSpec, TypeVar

# ParamSpec 和 TypeVar 用于在装饰器中 100% 保留原函数的入参和返回值类型提示
P = ParamSpec("P")
R = TypeVar("R")


def async_timer[**P, R](
    func: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    """统计异步函数执行耗时的切面装饰器"""

    @functools.wraps(func)  # 保留原函数的 __name__，__doc__ 和类型签名
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        start_time = time.perf_counter()
        try:
            return await func(*args, **kwargs)
        finally:
            # 无论成功还是抛异常，finally 块都会执行耗时统计
            elapsed = (time.perf_counter() - start_time) * 1000
            print(f"⏱️ [Trace] 函数 {func.__name__} 执行耗时: {elapsed:.2f} ms")

    return wrapper


def async_retry(max_retries: int = 3, base_delay: float = 0.5):
    """带参数的装饰器：用于大模型 API 偶发超市或触发 RateLimit 时的指数退避重试"""

    def decorator(
        func: Callable[P, Coroutine[Any, Any, R]],
    ) -> Callable[P, Coroutine[Any, Any, R]]:

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            last_error: Exception | None = None
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    last_error = exc
                    if attempt == max_retries:
                        print(
                            f"❌ [Retry] {func.__name__} 已达最大重试次数"
                            f"（{max_retries}），彻底失败"
                        )
                        raise
                    # 指数级别退避等待 0.5, 1.0, 2.0...
                    sleep_time = base_delay * (2 ** (attempt - 1))
                    print(
                        f"⚠️ [Retry] {func.__name__} 第 {attempt} 次调用异常: {exc}，"
                        f"{sleep_time:.1f}s 后重试..."
                    )
                    await asyncio.sleep(sleep_time)
            raise RuntimeError("Unreachable") from last_error

        return wrapper

    return decorator
