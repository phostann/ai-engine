import asyncio
from collections.abc import Callable, Coroutine
from typing import Any


async def run_bounded_task_group[T, R](
    items: list[T],
    worker_fn: Callable[[T], Coroutine[Any, Any, R]],
    *,
    max_concurrency: int = 3,
    timeout_per_item: float = 15.0,
) -> list[R]:
    """
    基于 Python 3.11+ TaskGroup + Semaphore + timeout 的结构化并发执行器
    要求：
    1. 限制最大同时运行的任务数不超过 max_concurrency
    2. 结果必须与输入 items 严格保持顺序一致
    3. 组内任一任务失败时，自动取消其他并发任务
    """
    if not items:
        return []

    # TODO 1: 实例化一个信号量，控制最大并发数
    semaphore = asyncio.Semaphore(max_concurrency)

    # 预分配槽位以确保返回结果与输入列表顺序严格一致
    results: list[R | None] = [None] * len(items)

    async def _worker_wrapper(index: int, item: T) -> None:
        # TODO 2: 使用 async with semaphore 限制并发访问
        # TODO 3: 在信号量内部，使用 async with asyncio.timeout(timeout_per_time) 控制单项超市
        # 并将 worker_fn(item) 的返回值写入 results[index]
        async with semaphore:
            async with asyncio.timeout(timeout_per_item):
                results[index] = await worker_fn(item)

    # TODO 4: 使用 async with asyncio.TaskGroup() as tg 管理并发任务
    # 遍历 items，使用 tg.create_task 提交任务
    async with asyncio.TaskGroup() as tg:
        for idx, item in enumerate(items):
            tg.create_task(_worker_wrapper(idx, item))

    return [r for r in results if r is not None]
