"""Audit-fix guard (2026-11): the v3 forward test is live, and its prompt fingerprint hashes the source text of 14
functions plus the ranking prompt, schema, strategy menu and TOP_AI (webapp/ai_test.py prompt_fingerprint;
docs/audit/fingerprint_map.md). No audit fix may change it until the user decides at Gate 2. A failure here means
STOP: undo the change to fingerprinted code."""

import pytest

from webapp import ai_test

V3_FINGERPRINT = "5a5fdbb32e977360b8ed0c9fa45107bbd7ddc315299b825d168f79d4fbc89bd4"


@pytest.mark.unit
def test_the_v3_prompt_fingerprint_is_unchanged():
    assert ai_test.prompt_fingerprint() == V3_FINGERPRINT
    assert ai_test.read_spec()["version"]["prompt_sha256"] == V3_FINGERPRINT
