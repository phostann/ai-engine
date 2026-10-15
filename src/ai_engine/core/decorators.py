import asyncio
import functools
from collections.abc import Callable, Coroutine
from typing import Any, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")
