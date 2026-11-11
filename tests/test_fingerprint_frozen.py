"""Guard: the v4 forward test is live (frozen 2026-11-11, docs/PA_54), and its prompt fingerprint hashes the source text
of 17 functions plus the ranking prompt, schema, strategy menu, TOP_AI and TAPE_ALLOWS (webapp/ai_test.py
prompt_fingerprint; docs/audit/fingerprint_map.md). A failure here means STOP: undo the change to fingerprinted code,
or the user freezes a new test."""

import pytest

from webapp import ai_test

V4_FINGERPRINT = "0698d1cae660b037fefc6289875f8028a7d20301614dc56b87f94658187fdf95"


@pytest.mark.unit
def test_the_v4_prompt_fingerprint_is_unchanged():
    assert ai_test.prompt_fingerprint() == V4_FINGERPRINT
    assert ai_test.read_spec()["version"]["prompt_sha256"] == V4_FINGERPRINT
