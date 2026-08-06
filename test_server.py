import unittest

from fastmcp import Client

import server
from dependency_versions import dependency_versions


class DependencyVersionTests(unittest.TestCase):
    def test_reports_pinned_runtime_dependencies(self):
        versions = dependency_versions()

        self.assertEqual(versions["fastmcp"], "3.4.4")
        self.assertEqual(versions["uvicorn"], "0.51.0")
        self.assertEqual(versions["starlette"], "1.3.1")

    def test_health_uses_dependency_version_report(self):
        self.assertEqual(server.health()["dependencies"], dependency_versions())


class InvokeToolArgsCompatibilityTests(unittest.TestCase):
    def test_accepts_native_args_object(self):
        result = server.invoke_tool(
            "list_directory",
            {"path": "/definitely-not-present"},
        )

        self.assertNotEqual(result.get("error"), "args must be an object")

    def test_accepts_json_encoded_args_object(self):
        result = server.invoke_tool(
            "list_directory",
            '{"path": "/definitely-not-present"}',
        )

        self.assertNotIn("args must be", result.get("error", ""))

    def test_rejects_json_encoded_non_object(self):
        result = server.invoke_tool("list_directory", '["/tmp"]')

        self.assertEqual(
            result,
            {
                "ok": False,
                "error": "args must be an object or a JSON-encoded object",
            },
        )

    def test_rejects_malformed_json(self):
        result = server.invoke_tool("list_directory", '{"path":')

        self.assertFalse(result["ok"])
        self.assertIn("args must be an object or a JSON-encoded object", result["error"])


class InvokeToolProtocolCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_fastmcp_accepts_json_encoded_args_object(self):
        async with Client(server.mcp) as client:
            result = await client.call_tool(
                "invoke_tool",
                {
                    "name": "list_directory",
                    "args": '{"path": "/definitely-not-present"}',
                },
            )

        self.assertFalse(result.is_error)
        self.assertNotIn("args must be", str(result.content))


if __name__ == "__main__":
    unittest.main()
