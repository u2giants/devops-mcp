import hashlib
import json
from pathlib import Path
import unittest


MANIFEST_PATH = Path(__file__).parent / "tests/fixtures/protocol-conformance-contract.json"
EXPECTED_CASE_IDS = [
    "MCP20260728-001-discover-supported-revisions",
    "MCP20260728-002-july-request-with-per-request-meta",
    "MCP20260728-003-supported-legacy-client-initializes",
    "MCP20260728-004-unsupported-version-error",
    "MCP20260728-005-july-client-needs-no-initialize",
    "MCP20260728-006-missing-static-bearer-challenge",
    "MCP20260728-007-invalid-static-bearer-challenge",
    "MCP20260728-008-bogus-session-header-is-harmless",
    "MCP20260728-009-deterministic-cacheable-tools-list",
    "MCP20260728-010-result-type-and-server-info",
    "MCP20260728-011-disconnect-stops-or-transfers-work",
    "MCP20260728-012-restart-between-independent-calls",
    "MCP20260728-013-deadline-error-and-work-stopped",
    "MCP20260728-014-health-redacts-sensitive-data",
    "MCP20260728-015-host-origin-validation",
    "MCP20260728-016-legacy-sse-transition",
    "MCP20260728-017-proxy-and-bridge-compatibility",
    "MCP20260728-018-required-method-and-name-headers",
    "MCP20260728-019-subscriptions-listen-and-legacy-get",
    "MCP20260728-020-may-server-not-initialized-hang-regression",
    "MCP20260728-021-cross-repo-contract-digest",
]


class ProtocolContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_versioned_contract_has_all_stable_case_ids(self):
        manifest = self.manifest
        self.assertEqual(manifest["contractVersion"], "1.0.0")
        self.assertEqual(manifest["wireRevision"], "2026-07-28")
        self.assertEqual(manifest["digestAlgorithm"], "sha256")

        cases = manifest["cases"]
        self.assertEqual(len(cases), 21)
        ids = [case["id"] for case in cases]
        self.assertEqual(ids, EXPECTED_CASE_IDS)
        for case in cases:
            self.assertTrue(case["summary"], case["id"])
            self.assertTrue(case["assertions"], case["id"])

    def test_contract_content_matches_approved_digest(self):
        manifest = self.manifest
        digest_input = {
            "contractVersion": manifest["contractVersion"],
            "wireRevision": manifest["wireRevision"],
            "cases": manifest["cases"],
        }
        canonical = json.dumps(
            digest_input,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        actual_digest = hashlib.sha256(canonical).hexdigest()
        self.assertEqual(actual_digest, manifest["expectedDigest"])


if __name__ == "__main__":
    unittest.main()
