import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).parent.parent
WORKFLOW = (REPOSITORY / ".github/workflows/ci.yml").read_text(encoding="utf-8")


def test_workflow_has_minimal_permissions_at_the_top_level():
    assert "\npermissions:\n  contents: read\n" in WORKFLOW
    assert WORKFLOW.count("permissions:") == 1
    assert "write" not in WORKFLOW


def test_every_action_is_pinned_to_a_full_commit_sha():
    actions = re.findall(r"uses:\s*(\S+)", WORKFLOW)
    assert actions
    for action in actions:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", action), action


def test_checkout_does_not_keep_credentials():
    assert "persist-credentials: false" in WORKFLOW


def test_workflow_runs_every_required_check():
    assert "container: archlinux:base" in WORKFLOW
    assert "nodejs" in WORKFLOW
    assert "(3, 14)" in WORKFLOW
    assert ".venv/bin/ruff check ." in WORKFLOW
    assert ".venv/bin/ruff format --check ." in WORKFLOW
    assert "PIPELINE_FAIL_ON_SKIP=1 .venv/bin/pytest" in WORKFLOW


@pytest.mark.parametrize(("fail_on_skip", "expected"), [(True, 1), (False, 0)])
def test_skipped_tests_fail_only_when_required(tmp_path, fail_on_skip, expected):
    (tmp_path / "test_sample.py").write_text(
        'import pytest\n\n\n@pytest.mark.skip(reason="sample")\ndef test_skipped():\n    pass\n',
        encoding="utf-8",
    )
    environment = {
        key: value for key, value in os.environ.items() if key != "PIPELINE_FAIL_ON_SKIP"
    }
    environment["PYTHONPATH"] = str(REPOSITORY / "tests")
    if fail_on_skip:
        environment["PIPELINE_FAIL_ON_SKIP"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "conftest",
            "--rootdir",
            str(tmp_path),
            str(tmp_path),
        ],
        env=environment,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == expected, result.stdout
