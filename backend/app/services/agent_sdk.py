"""单次模型执行适配；业务提示词、JSON 修复和重试策略仍由 rag.llm 持有。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, cast

import httpx
from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from app.config import settings
from app.errors import AppError

if TYPE_CHECKING:
    from agents import (
        Agent, RunErrorHandlerInput, RunErrorHandlerResult, StreamEvent, TResponseInputItem,
    )


def prepare_runtime() -> None:
    """惰性检查 SDK 依赖，并在首次执行前移除默认云端追踪出口。"""
    try:
        sdk = import_module("agents")
        for name in (
            "Agent", "Runner", "OpenAIChatCompletionsModel", "ModelSettings", "ModelRetrySettings",
        ):
            getattr(sdk, name)
        from app.services import agent_tracing

        agent_tracing.initialize()
        if not agent_tracing.execution_provider_available():
            raise ImportError("SDK execution provider unavailable")
    except (ImportError, AttributeError) as exc:
        raise AppError(
            "AGENT_RUNTIME_UNAVAILABLE", "智能出题运行环境暂不可用，请稍后重试", 503,
        ) from exc


def ensure_available() -> None:
    """供业务入口在受理 SDK run 前检查执行依赖。"""
    prepare_runtime()


@dataclass
class _StreamState:
    response_started: bool = False

    async def on_response(self, response: httpx.Response) -> None:
        # create(stream=True) 成功后发生的 SSE 错误不属于原 legacy thinking 回退窗口。
        if response.is_success:
            self.response_started = True


def _new_client(api_key: str | None, state: _StreamState | None = None) -> AsyncOpenAI:
    key = api_key or settings.deepseek_api_key
    if not key:
        from app.services.rag.llm import LLMError

        raise LLMError("DeepSeek API Key 未配置：请到设置 → 模型与服务中填写")
    # 客户端只属于本次执行的私有事件循环，不放入 legacy 的跨线程缓存。
    return AsyncOpenAI(
        api_key=key,
        base_url=settings.deepseek_base_url,
        timeout=float(settings.llm_timeout_seconds),
        max_retries=0,
        http_client=DefaultAsyncHttpxClient(
            event_hooks={"response": [state.on_response]} if state is not None else None,
        ),
    )


def _agent(kwargs: dict[str, object], client: AsyncOpenAI, thinking_off: bool) -> Agent:
    from agents import Agent, ModelRetrySettings, ModelSettings, OpenAIChatCompletionsModel

    extra_args: dict[str, object] = {}
    if kwargs.get("response_format"):
        extra_args["response_format"] = kwargs["response_format"]
    model_settings = ModelSettings(
        temperature=cast(float, kwargs["temperature"]),
        max_tokens=cast("int | None", kwargs.get("max_tokens")),
        retry=ModelRetrySettings(max_retries=0),
        extra_args=extra_args,
        extra_body={"thinking": {"type": "disabled"}} if thinking_off else None,
    )
    return Agent(
        name="MathCraft",
        instructions=None,
        model=OpenAIChatCompletionsModel(model=cast(str, kwargs["model"]), openai_client=client),
        model_settings=model_settings,
        tools=[],
        handoffs=[],
        output_type=None,
    )


def _input(kwargs: dict[str, object]) -> list[TResponseInputItem]:
    # SDK 0.20 的 Converter 原生接受 Chat Completions text/image_url 别名并校验内容。
    # 不把 system 拆成 instructions，以免改变历史消息的顺序和 assistant 回喂内容。
    return cast("list[TResponseInputItem]", kwargs["messages"])


def _legacy_refusal(_data: RunErrorHandlerInput[object]) -> RunErrorHandlerResult:
    """保持 legacy 只读取 content 的行为，不因 SDK 拒绝处理而追加模型调用。"""
    from agents import RunErrorHandlerResult

    return RunErrorHandlerResult(final_output="", include_in_history=False)


async def _complete(kwargs: dict[str, object], api_key: str | None, thinking_off: bool) -> str:
    from agents import Runner

    async with _new_client(api_key) as client:
        try:
            result = await Runner.run(
                _agent(kwargs, client, thinking_off), input=_input(kwargs), max_turns=1,
                error_handlers={"model_refusal": _legacy_refusal},
            )
        except Exception as exc:
            if not thinking_off or "thinking" not in str(exc).lower():
                raise
            result = await Runner.run(
                _agent(kwargs, client, False), input=_input(kwargs), max_turns=1,
                error_handlers={"model_refusal": _legacy_refusal},
            )
        # final_output 是 SDK 的最终输出；从原始文本 item 取值，避免空白、拒绝处理等
        # SDK 最终输出格式化规则影响 chat_text 的原文契约。
        from openai.types.responses import ResponseOutputMessage, ResponseOutputText

        return "".join(
            part.text
            for response in result.raw_responses
            for item in response.output
            if isinstance(item, ResponseOutputMessage)
            for part in item.content
            if isinstance(part, ResponseOutputText)
        )


def complete(kwargs: dict[str, object], api_key: str | None, thinking_off: bool = False) -> str:
    """用真实 SDK Agent 执行一个模型回合，返回未经修改的文本。"""
    ensure_available()
    with asyncio.Runner() as loop_runner:
        return loop_runner.run(_complete(kwargs, api_key, thinking_off))


async def _stream(
    kwargs: dict[str, object], api_key: str | None, thinking_off: bool,
) -> AsyncGenerator[str, None]:
    from agents import Runner

    state = _StreamState()
    async with _new_client(api_key, state) as client:
        while True:
            result = Runner.run_streamed(
                _agent(kwargs, client, thinking_off), input=_input(kwargs), max_turns=1,
                error_handlers={"model_refusal": _legacy_refusal},
            )
            # 锁定版本的 stream_events 实现是 async generator；其接口标注较宽。
            events = cast("AsyncGenerator[StreamEvent, None]", result.stream_events())
            try:
                async for event in events:
                    if event.type != "raw_response_event":
                        continue
                    if event.data.type == "response.output_text.delta" and event.data.delta:
                        yield event.data.delta
                return
            except Exception as exc:
                if state.response_started or not thinking_off or "thinking" not in str(exc).lower():
                    raise
                thinking_off = False
            finally:
                # cancel 先停止 SDK 后台执行；随后关闭事件迭代器并等待任务，确保
                # OpenAIChatCompletionsModel 的 finally 有机会关闭 provider HTTP 流。
                result.cancel()
                try:
                    await events.aclose()
                finally:
                    if result.run_loop_task is not None:
                        await asyncio.gather(result.run_loop_task, return_exceptions=True)


async def _next_text(iterator: AsyncIterator[str]) -> str:
    return await anext(iterator)


async def _close_stream(iterator: AsyncGenerator[str, None]) -> None:
    await iterator.aclose()


def stream(
    kwargs: dict[str, object], api_key: str | None, thinking_off: bool = False,
) -> Iterator[str]:
    """在同一个私有循环中同步拉取文本 delta，并在提前关闭或失败时释放全部资源。"""
    ensure_available()
    with asyncio.Runner() as loop_runner:
        iterator = _stream(kwargs, api_key, thinking_off)
        try:
            while True:
                try:
                    piece = loop_runner.run(_next_text(iterator))
                except StopAsyncIteration:
                    return
                yield piece
        finally:
            loop_runner.run(_close_stream(iterator))
