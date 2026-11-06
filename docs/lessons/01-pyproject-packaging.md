# pyproject.toml 与 Python 项目打包

> 本文逐字转录自原始课程对话，只添加角色标题和来源信息，未改写、删减或二次总结。
>
- 返回：[课程原文索引](README.md)
- 原始消息序号：`350`、`355`、`362`、`404`

## 用户（原始消息 350）

uv 可以跳过，我自己通读了uv 的文档，已经很清楚了

## 助手（原始消息 355）

可以，`uv` 从课程中移除，直接进入下一个知识点。

**知识点 02：`pyproject.toml` 与 Python 项目打包**

这一课只讲 `C:\work\python\ai-agent-leran\ai-engine\pyproject.toml`，不混入环境变量、Pydantic 和异步。

## 1. 它解决的问题

`pyproject.toml` 不是 uv 专用文件，而是现代 Python 项目的统一声明文件。它回答四个问题：

1. 这个项目叫什么、版本是多少？
2. 运行时需要哪些依赖？
3. 开发时需要哪些工具？
4. 使用什么工具把项目构建成可安装包？

它本身不会安装依赖，也不会启动程序。真正读取它的是 uv、构建工具、Ruff、测试工具等。

## 2. 整体结构

你的文件可以分成五块：

```toml
[project]           # 项目元数据和运行依赖
[project.scripts]   # 命令行入口
[build-system]      # 构建后端
[dependency-groups] # 开发依赖
[tool.ruff]         # 工具配置
```

其中前四块与 Python 打包有关，`[tool.ruff]` 只是 Ruff 的配置。

## 3. `[project]`：项目身份与运行依赖

```toml
[project]
name = "ai-engine"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "httpx>=0.28.1",
    "pydantic>=2.14.1",
]
```

这里最重要的是 `name`：

```toml
name = "ai-engine"
```

它是**发布名称**，可以带连字符。

但导入名称是：

```python
import ai_engine
```

它是**Python 包名**，使用下划线。

所以：

```text
项目发布名：ai-engine
Python 导入名：ai_engine
```

两者不需要完全相同，但必须让构建工具知道 `ai_engine` 这个包在哪里。

`dependencies` 表示生产运行依赖。项目安装后，这些包必须存在，否则程序无法运行。

```toml
pydantic-settings==2.16.1
```

表示精确版本。

```toml
fastapi>=0.115.0
```

表示最低版本约束，允许更高版本。

项目通常不会把所有依赖都写死精确版本，而是：

```text
pyproject.toml：声明可接受的版本范围
uv.lock：锁定本次实际解析出的精确版本
```

这样既能表达兼容范围，也能保证不同机器安装出一致的依赖树。

`uvicorn[standard]` 中的 `[standard]` 是可选依赖组，也叫 extras。它表示除了 uvicorn 核心包，还要安装一组用于性能和完整功能的附加依赖。

`requires-python = ">=3.12"` 不只是编辑器提示，它还参与依赖解析和包安装。如果运行环境低于 Python 3.12，安装工具可以拒绝安装。

## 4. `[build-system]`：谁负责构建项目

```toml
[build-system]
requires = ["uv_build>=0.13.0,<0.14.0"]
build-backend = "uv_build"
```

这部分容易被忽略。

`requires` 不是应用运行依赖，而是**构建项目时需要的依赖**。构建工具会先安装它，再读取 `build-backend` 指定的构建后端。

`build-backend` 的作用是：

```text
读取 pyproject.toml
    ↓
找到 Python 包
    ↓
生成 wheel 或源码包
    ↓
生成安装元数据
```

常见构建后端包括：

- `setuptools.build_meta`
- `hatchling.build`
- `uv_build`
- `flit_core.buildapi`

它们产出的 Python 包通常有两种形式：

- wheel：`.whl`，可以直接安装的构建产物。
- sdist：源码分发包，安装时可能需要重新构建。

这里的 `uv_build` 会按照项目结构寻找包。你的源码位于：

```text
src/ai_engine/
```

所以构建后才能把 `ai_engine` 安装进虚拟环境。

`pyproject.toml` 本身不会被打包进 wheel 作为运行逻辑，它只是构建和安装时的元数据来源。

## 5. `[project.scripts]`：命令行入口

```toml
[project.scripts]
ai-engine = "ai_engine:main"
```

这行的含义是：

```text
命令名称：ai-engine
模块：ai_engine
函数：main
```

安装项目后，会生成一个命令行程序。执行：

```powershell
uv run ai-engine
```

大致等价于：

```python
from ai_engine import main
main()
```

`ai_engine:main` 中的冒号左边是模块，右边是函数或可调用对象。

这个函数必须存在，否则安装后执行命令会报导入错误。

入口点适合：

- CLI 工具
- 后台任务启动器
- 服务启动命令
- 运维脚本

它不适合直接写复杂逻辑。入口函数应该只负责调用真正的业务入口，例如 `asyncio.run(...)`，把逻辑留在其他模块中。

## 6. `[dependency-groups]`：开发依赖

```toml
[dependency-groups]
dev = [
    "pytest>=9.1.1",
    "pytest-asyncio>=1.4.0",
    "ruff>=0.17.0",
]
```

开发依赖和运行依赖必须区分：

- `dependencies`：部署和生产运行必须安装。
- `dependency-groups.dev`：开发、测试、格式化时安装。

生产环境不应该无意义地安装 `pytest` 和 `ruff`，这会增加镜像体积、攻击面和依赖冲突概率。

开发依赖组不等于 Python 的可选依赖。可选依赖通常通过 extras 暴露给使用者，而开发依赖组主要服务于项目自身的开发流程。

## 7. `[tool.ruff]`：工具配置

```toml
[tool.ruff]
line-length = 100
target-version = "py312"
src = ["src"]
```

这部分不影响运行逻辑，但会影响代码质量和导入分析。

- `line-length`：格式化宽度。
- `target-version`：按 Python 3.12 语法规则检查。
- `src`：告诉 Ruff 到 `src` 下寻找项目模块。

后面的：

```toml
select = ["E", "W", "F", "I", "B", "UP"]
```

分别覆盖基础风格、未使用变量、导入顺序、潜在 Bug 和旧语法升级。

这部分属于工具链知识，不是 Python 运行时行为。

## 8. 从配置到安装的完整链路

```text
pyproject.toml
    声明项目名称、依赖、构建后端、入口点
            ↓
uv / 构建工具读取
            ↓
解析依赖并生成 uv.lock
            ↓
创建虚拟环境
            ↓
安装依赖和当前项目
            ↓
生成 ai-engine 命令
            ↓
执行 ai_engine:main
```

这就是为什么修改 `pyproject.toml` 后，有时需要重新同步环境，而不只是重新运行 Python 文件。

## 9. 常见错误

- 把 `ai-engine` 当成导入名，写成 `import ai-engine`。
- 修改了 `pyproject.toml`，但没有重新同步依赖。
- 把 `pytest` 放进生产依赖。
- 把 `build-system.requires` 当成应用运行依赖。
- 入口点写成了不存在的模块或函数。
- 只改 `pyproject.toml` 版本范围，却不知道锁文件仍然固定旧版本。
- 认为 `uv.lock` 会被打进 wheel。它主要服务于项目开发时的可重复安装。
- 认为 `[tool.ruff]` 会影响程序运行。它只影响工具行为。

## 10. 本课练习

只改 `pyproject.toml` 或使用构建命令，不要改业务代码。

1. 解释 `ai-engine` 和 `ai_engine` 分别是什么。
2. 执行 `uv build`，观察生成了哪些文件，并说明 wheel 和 sdist 的区别。
3. 用 `uv run ai-engine` 运行当前入口，说明它最终调用了哪个函数。
4. 把 `pytest` 从开发依赖移到运行依赖，思考为什么这是不合理的。
5. 说明 `uvicorn[standard]` 中 `[standard]` 的含义。
6. 说明 `[build-system].requires` 和 `[project].dependencies` 的区别。
7. 解释为什么修改 `pyproject.toml` 后可能需要重新执行同步命令。

## 验收标准

你需要能够不查资料回答：

- `pyproject.toml` 的五类主要配置分别负责什么？
- 项目发布名、Python 包名、命令行入口名分别是什么？
- `build-system` 和 `dependencies` 为什么不是一回事？
- `pyproject.toml`、`uv.lock`、wheel 三者分别扮演什么角色？
- `ai-engine = "ai_engine:main"` 是如何工作的？

下一课只讲 **Python 包、模块与导入机制**：`src` 布局、`__init__.py`、`import` 查找过程、editable install，以及为什么当前项目能使用 `ai_engine` 这个导入名。

## 用户（原始消息 362）

1. ai-engine 是项目名，发布的时候的名字，而 ai_engine 才是真正的包名 2. uv build 生成了 .whl 和 .tar.gz 两种文件， wheel 是构建好的包，直接就能使用，而 sdist 是以源码形式分发，需要使用方自行构建。 3. uv run ai-engine 最终调用了 **init**.py 这个我不太清楚，你分析代码后为我讲解。4. 开发依赖转为运行依赖会导致包体积增加，依赖冲突风险增加，被攻击风险增加。5. standard 指的是 uvicorn 自己的依赖分组名字  6. `[build-system].requires`   是构建时需要的依赖，和代码运行无关7. 修改后 lock 文件没变，所以解析出的版本还是以前的，因而需要进行同步操作 例如 uv sync

## 助手（原始消息 404）

整体答得不错，核心方向基本正确。逐题批改如下。

**1. 项目名与包名**
正确。

- `ai-engine`：分发包名称，也就是发布到包仓库时的名字。
- `ai_engine`：Python 导入包名称。
- `ai-engine` 会生成命令行 `ai-engine.exe`。
- 构建产物文件名会做规范化，所以是 `ai_engine-0.1.0-py3-none-any.whl`。

**2. wheel 与 sdist**
基本正确，补充两个细节：

- wheel 不是“直接运行”的文件，而是“可以被安装工具直接安装”的构建产物。安装后仍然需要 Python 和依赖环境。
- sdist 通常不需要使用者手动构建；`pip` 或 `uv` 安装 sdist 时，通常会先自动构建 wheel，只是这个过程可能需要编译工具链。
- 你的项目是纯 Python 包，因此 wheel 名称里是 `py3-none-any`。

**3. `uv run ai-engine` 的调用链**
你的方向对了一半：确实和 `src\ai_engine\__init__.py` 有关，但不是“调用 `__init__.py` 这个文件”。

正确说法是：

```text
uv run ai-engine
    ↓
运行 .venv\Scripts\ai-engine.exe
    ↓
导入 ai_engine 包
    ↓
执行 src\ai_engine\__init__.py
    ↓
取得包里的 main 函数
    ↓
调用 main()
    ↓
main() 执行 asyncio.run(async_main())
```

### 第一步：`pyproject.toml` 声明入口

```toml
[project.scripts]
ai-engine = "ai_engine:main"
```

含义是：

```text
命令名：ai-engine
模块：ai_engine
属性：main
```

安装项目后，构建工具会在安装元数据中写入：

```text
C:\work\python\ai-agent-leran\ai-engine\.venv\Lib\site-packages\ai_engine-0.1.0.dist-info\entry_points.txt
```

内容就是：

```ini
[console_scripts]
ai-engine = ai_engine:main
```

同时生成了实际命令：

```text
C:\work\python\ai-agent-leran\ai-engine\.venv\Scripts\ai-engine.exe
```

这个 exe 是启动器，不包含你的业务逻辑。

### 第二步：导入 `ai_engine` 包

执行 `ai-engine` 时，启动器会做类似下面的事情：

```python
import ai_engine
ai_engine.main()
```

导入 `ai_engine` 时，Python 会找到：

```text
C:\work\python\ai-agent-leran\ai-engine\src\ai_engine\__init__.py
```

并从上到下执行这个文件。

当前项目是 editable install。安装信息中有一个：

```text
C:\work\python\ai-agent-leran\ai-engine\.venv\Lib\site-packages\ai_engine.pth
```

它指向：

```text
C:\work\python\ai-agent-leran\ai-engine\src
```

所以 Python 能找到 `src\ai_engine`，同时修改源码后不需要重新安装。

### 第三步：执行 `__init__.py`

`__init__.py` 执行时，会做这些事情：

```python
import asyncio

from ai_engine.core.config import get_settings
from ai_engine.core.context import llm_session_scope
from ai_engine.services.stream_service import check_model_health, stream_llm_tokens
```

这些导入会加载配置模块、异步上下文模块和流服务模块。

然后定义两个函数：

```python
async def async_main() -> None:
    ...

def main() -> None:
    asyncio.run(async_main())
```

注意：**定义函数不等于调用函数**。导入阶段只是把 `async_main` 和 `main` 放进 `ai_engine` 模块的命名空间。

因此此时：

```python
ai_engine.main
```

是存在的，但还没有执行。

### 第四步：入口点调用 `main`

启动器拿到 `ai_engine.main` 后调用：

```python
main()
```

`main` 的函数体是：

```python
asyncio.run(async_main())
```

于是进入异步主流程。

### 第五步：`async_main()` 做了什么

```python
async def async_main() -> None:
    settings = get_settings()

    async with llm_session_scope(settings.llm_model) as client:
        await check_model_health(client, simulate_fail=True)

        async for token in stream_llm_tokens(client, "什么是异步生成器？"):
            print(token, end="", flush=True)
```

流程是：

1. 读取配置。
2. 创建模拟 LLM 客户端会话。
3. 调用健康检查，并且故意模拟一次失败，用来触发重试。
4. 消费异步 Token 流。
5. 用户模拟中断时，通过 `stream.aclose()` 触发生成器清理。
6. 退出 `async with` 后关闭客户端会话。
7. `asyncio.run()` 最后关闭事件循环。

### 所以最准确的表述是

```text
uv run ai-engine
= 执行安装生成的命令行启动器
= 导入 ai_engine 包
= 执行 ai_engine/__init__.py
= 取得并调用其中的 main()
= asyncio.run(async_main())
```

不是：

```text
uv run ai-engine = 直接调用 __init__.py
```

另外，`import ai_engine` 会执行 `__init__.py`，但不会自动调用 `main()`。只有入口点启动器显式调用了它。

### 一个设计上的注意点

把 `main()` 和业务入口放在 `__init__.py` 里不是最佳实践。更常见的结构是：

```text
src/ai_engine/__init__.py   # 只做轻量导出
src/ai_engine/cli.py        # 放 main()
```

然后配置：

```toml
[project.scripts]
ai-engine = "ai_engine.cli:main"
```

原因是 `__init__.py` 在每次导入包时都会执行。如果里面放了数据库连接、读配置、启动服务等副作用，任何 `import ai_engine` 都会触发它们，容易产生隐蔽问题。

**4. 开发依赖与运行依赖**
正确。补充一点：开发依赖进入运行环境不仅增加体积，还会扩大攻击面、增加版本冲突概率，并让生产镜像包含不需要的测试和代码检查工具。

**5. `uvicorn[standard]`**
基本正确，但更准确地说：

- `standard` 是 **uvicorn 这个第三方包定义的 extras 组**。
- 不是你的 `pyproject.toml` 定义的依赖组。
- 安装它会额外拉取 uvicorn 推荐的性能或功能依赖。
- extras 是包作者暴露的可选安装能力。

**6. `build-system.requires`**
你的核心理解正确：它是构建时依赖，不是运行依赖。

更完整的区别是：

- `[build-system].requires`：构建 wheel/sdist 时，在隔离构建环境中安装的依赖。
- `[project].dependencies`：安装并使用项目时，在运行环境中安装的依赖。
- `build-backend`：真正执行构建逻辑的后端，例如 `uv_build`。
- 构建依赖通常不会自动成为应用运行依赖，也不会原样进入 wheel。

**7. 修改配置后的同步**
方向正确，但补充精确行为：

- 手工修改 `pyproject.toml` 不会自动修改 `uv.lock`。
- 手工修改 `pyproject.toml` 也不会自动修改 `.venv`。
- 默认执行 `uv sync` 时，如果锁文件过期，uv 会更新锁文件，然后同步环境。
- `uv sync --locked` 要求锁文件已经是最新，不会更新锁文件。
- `uv sync --frozen` 使用现有锁文件，不重新解析。
- CI 中常用 `--locked`，避免依赖解析结果意外变化。

你的整体掌握情况不错，主要缺口是**入口点机制**和**构建产物、锁文件、同步动作之间的精确关系**。

下一课进入 **Python 包、模块与导入机制**，重点讲清楚：

- `ai_engine` 如何被 Python 找到
- `__init__.py` 的真实作用
- `.pth` 文件与 editable install
- `python -m ai_engine` 和 `uv run ai-engine` 的区别
- 为什么 `import ai_engine.main`、`from ai_engine import main`、`from ai_engine.__init__ import main` 行为不同

