"""Real-provider smoke-tool safety tests using only an in-memory fake transport."""

from importlib.metadata import PackageNotFoundError, version
import unittest

try:
    AVAILABLE = all(
        version(name) == expected
        for name, expected in {
            "openai-agents": "0.20.0",
            "openinference-instrumentation-openai-agents": "2.7.0",
            "opentelemetry-exporter-otlp-proto-http": "1.45.2",
        }.items()
    )
except PackageNotFoundError:
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, "Use the isolated tools/ops_g0 environment")
class LiveBudgetTests(unittest.IsolatedAsyncioTestCase):
    """Prove credentials cannot reach unapproved hosts or exceed the paid budget."""

    async def test_unapproved_target_is_rejected_before_transport(self) -> None:
        import httpx
        from tools.ops_g0.live_smoke import ModelTransport

        reached = []
        fake = httpx.MockTransport(lambda request: reached.append(request) or httpx.Response(200))
        transport = ModelTransport("synthetic-model", transport=fake)
        for url in (
            "https://fixture.invalid/chat/completions",
            "http://api.deepseek.com/chat/completions",
            "https://api.deepseek.com/other",
            "https://api.deepseek.com/chat/completions?key=fake",
        ):
            with self.assertRaises(PermissionError):
                await transport.handle_async_request(
                    httpx.Request(
                        "POST",
                        url,
                        json={
                            "model": "synthetic-model",
                            "max_tokens": 128,
                        },
                    )
                )
        self.assertEqual(reached, [])
        await transport.aclose()

    async def test_output_limit_and_model_identity_are_enforced(self) -> None:
        import httpx
        from tools.ops_g0.live_smoke import ModelTransport

        reached = []
        fake = httpx.MockTransport(lambda request: reached.append(request) or httpx.Response(200))
        transport = ModelTransport("synthetic-model", transport=fake)
        for model, tokens in (
            ("other-model", 128),
            ("synthetic-model", 129),
            ("synthetic-model", 0),
        ):
            with self.assertRaises(PermissionError):
                await transport.handle_async_request(
                    httpx.Request(
                        "POST",
                        "https://api.deepseek.com/chat/completions",
                        json={"model": model, "max_tokens": tokens},
                    )
                )
        self.assertEqual(reached, [])
        await transport.aclose()

    async def test_fourth_paid_request_is_rejected(self) -> None:
        import httpx
        from tools.ops_g0.live_smoke import ModelTransport

        reached = []
        fake = httpx.MockTransport(lambda request: reached.append(request) or httpx.Response(200))
        transport = ModelTransport("synthetic-model", transport=fake)
        request = httpx.Request(
            "POST",
            "https://api.deepseek.com/chat/completions",
            json={"model": "synthetic-model", "max_tokens": 128},
        )
        for _ in range(3):
            await transport.handle_async_request(request)
        with self.assertRaises(PermissionError):
            await transport.handle_async_request(request)
        self.assertEqual(len(reached), 3)
        self.assertEqual(len(transport.calls), 3)
        await transport.aclose()
