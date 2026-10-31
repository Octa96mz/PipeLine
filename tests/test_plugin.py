import json
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline import __version__
from pipeline.collector import DUE_TOLERANCE_SECONDS
from pipeline.config import Config
from pipeline.db import Database
from pipeline.report import SCHEMA_VERSION, build_report, error_report
from synthetic import NOW

REPOSITORY = Path(__file__).parent.parent
PLUGIN = REPOSITORY / "plugin"
NODE = shutil.which("node")

needs_node = pytest.mark.skipif(NODE is None, reason="node no está instalado")

_RUNNER = """
const fs = require("fs"), vm = require("vm");
const context = {};
vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), context);
const input = JSON.parse(fs.readFileSync(0, "utf8"));
console.log(JSON.stringify(context[input.call](...input.args) ?? null));
"""


def model(function, *args):
    result = subprocess.run(
        [NODE, "-e", _RUNNER, "--", str(PLUGIN / "Model.js")],
        input=json.dumps({"call": function, "args": args}),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(result.stdout)


def real_report(tmp_path, *setup):
    with Database.open(tmp_path / "pipeline.db") as database:
        for step in setup:
            step(database)
        return json.loads(json.dumps(build_report(Config(), database, NOW)))


def test_manifest_matches_the_project():
    manifest = json.loads((PLUGIN / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "pipeline.market"
    assert manifest["version"] == __version__
    assert manifest["kinds"] == ["bar-widget"]
    assert (PLUGIN / manifest["entryPoints"]["barWidget"]).is_file()


def test_widget_only_reads_through_the_cli_with_a_timeout():
    source = (PLUGIN / "Widget.qml").read_text(encoding="utf-8")
    assert 'command: ["timeout", "-k", "1", "3", root.command, "json"]' in source
    for forbidden in ("https://", "XMLHttpRequest", '"fetch"', "bash", "/home/"):
        assert forbidden not in source


@needs_node
def test_model_and_python_agree_on_the_schema_version():
    assert model("parseReport", "{}", None)["failed"] is True
    source = (PLUGIN / "Model.js").read_text(encoding="utf-8")
    assert f"var SCHEMA_VERSION = {SCHEMA_VERSION}" in source


@needs_node
def test_model_reads_a_real_report(tmp_path):
    report = real_report(tmp_path)
    result = model("parseReport", json.dumps(report), None)
    assert result["failed"] is False
    assert result["report"]["status"] == "no_data"
    items = model("barItems", result)
    assert [item["label"] for item in items] == ["BTC", "S&P"]
    assert {item["role"] for item in items} == {"none"}
    assert items[0]["value"] == "—"
    assert model("tooltip", result) == report["bar"]["tooltip"]


@needs_node
@pytest.mark.parametrize("text", ["", "not json", "null", '{"schema_version": 99}'])
def test_unusable_output_keeps_the_previous_report(text):
    previous = {"schema_version": 1, "bar": {"items": [], "tooltip": "Anterior"}}
    result = model("parseReport", text, previous)
    assert result["failed"] is True
    assert result["report"] == previous
    assert model("tooltip", result).endswith("\nAnterior")
    assert model("tooltip", result).startswith("No se pudo actualizar")


@needs_node
def test_error_report_keeps_the_previous_data_and_shows_the_reason():
    previous = {"schema_version": 1, "bar": {"items": [], "tooltip": "Anterior"}}
    text = json.dumps(error_report("base de datos dañada", NOW))
    result = model("parseReport", text, previous)
    assert result["failed"] is True
    assert result["report"] == previous
    assert "base de datos dañada" in model("tooltip", result)


@needs_node
def test_first_failure_has_a_tooltip_and_no_items():
    result = model("parseReport", "", None)
    assert model("barItems", result) == []
    assert "No se pudo actualizar" in model("tooltip", result)


@needs_node
@pytest.mark.parametrize(
    ("state", "direction", "failed", "role", "glyph"),
    [
        ("fresh", "up", False, "up", "▲"),
        ("fresh", "down", False, "down", "▼"),
        ("fresh", "flat", False, "flat", ""),
        ("fresh", None, False, "flat", ""),
        # Un dato obsoleto no se pinta de verde ni de rojo.
        ("stale", "up", False, "stale", ""),
        ("stale", "down", False, "stale", ""),
        ("fresh", "up", True, "stale", ""),
        ("held", "up", False, "held", "!"),
        ("held", "up", True, "held", "!"),
        ("no_data", None, False, "none", ""),
        ("unavailable", None, False, "none", ""),
    ],
)
def test_color_follows_the_variation_only_for_fresh_data(state, direction, failed, role, glyph):
    assert model("colorRole", state, direction, failed) == role
    assert (model("glyph", role) or "") == glyph


@needs_node
def test_failed_read_marks_saved_items_as_stale():
    report = {
        "schema_version": 1,
        "status": "fresh",
        "bar": {
            "tooltip": "t",
            "items": [{"label": "BTC", "value_text": "1000", "state": "fresh", "direction": "up"}],
        },
    }
    failed = model("parseReport", "", report)
    assert model("barItems", failed) == [
        {"label": "BTC", "value": "1000", "glyph": "", "role": "stale"}
    ]


@needs_node
def test_no_result_yet_is_handled():
    assert model("barItems", None) == []
    assert model("tooltip", None) == "PipeLine: cargando"


def make_repository(tmp_path, name="repo"):
    root = tmp_path / name
    (root / "scripts").mkdir(parents=True)
    shutil.copy(REPOSITORY / "scripts/install-launcher.sh", root / "scripts")
    venv_bin = root / ".venv/bin"
    venv_bin.mkdir(parents=True)
    target = venv_bin / "pipeline"
    target.write_text('#!/bin/sh\necho "args:$*"\n', encoding="utf-8")
    target.chmod(0o755)
    return root, target


def run_installer(root, home):
    return subprocess.run(
        ["/bin/sh", str(root / "scripts/install-launcher.sh")],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_launcher_is_only_an_exec_to_the_venv(tmp_path):
    root, target = make_repository(tmp_path)
    home = tmp_path / "home"
    result = run_installer(root, home)
    assert result.returncode == 0, result.stderr
    launcher = home / ".local/bin/pipeline"
    assert launcher.read_text(encoding="utf-8") == f'#!/bin/sh\nexec {target.resolve()} "$@"\n'
    assert launcher.stat().st_mode & 0o777 == 0o755
    assert [item.name for item in launcher.parent.iterdir()] == ["pipeline"]
    run = subprocess.run(
        [str(launcher), "json", "--pretty"],
        env={},
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert run.stdout == "args:json --pretty\n"


def test_launcher_never_overwrites(tmp_path):
    root, _ = make_repository(tmp_path)
    home = tmp_path / "home"
    launcher = home / ".local/bin/pipeline"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("existing", encoding="utf-8")
    result = run_installer(root, home)
    assert result.returncode == 1
    assert "no se toca" in result.stderr
    assert launcher.read_text(encoding="utf-8") == "existing"
    assert [item.name for item in launcher.parent.iterdir()] == ["pipeline"]


def test_launcher_requires_the_venv(tmp_path):
    root, target = make_repository(tmp_path)
    target.unlink()
    home = tmp_path / "home"
    result = run_installer(root, home)
    assert result.returncode == 1
    assert not (home / ".local/bin/pipeline").exists()


def test_launcher_refuses_unsafe_paths(tmp_path):
    root, _ = make_repository(tmp_path, name="repo with space")
    home = tmp_path / "home"
    result = run_installer(root, home)
    assert result.returncode == 1
    assert "no admitidos" in result.stderr
    assert not (home / ".local/bin/pipeline").exists()


def test_repository_has_no_personal_paths():
    checked = [REPOSITORY / name for name in ("src", "plugin", "scripts", "docs", "systemd")]
    files = [path for folder in checked for path in folder.rglob("*") if path.is_file()]
    files += [REPOSITORY / name for name in ("README.md", "config.example.toml", "pyproject.toml")]
    for path in files:
        if path.suffix == ".pyc":
            continue
        assert "/home/" not in path.read_text(encoding="utf-8"), path


def unit_values(name, key):
    lines = (REPOSITORY / "systemd" / name).read_text(encoding="utf-8").splitlines()
    return [line.split("=", 1)[1] for line in lines if line.startswith(f"{key}=")]


def test_service_runs_only_the_scheduled_fetch_through_the_launcher():
    assert unit_values("pipeline-fetch.service", "Type") == ["oneshot"]
    assert unit_values("pipeline-fetch.service", "ExecStart") == [
        "%h/.local/bin/pipeline fetch --scheduled"
    ]


def test_service_can_only_write_its_data_directory():
    assert unit_values("pipeline-fetch.service", "ProtectSystem") == ["strict"]
    assert unit_values("pipeline-fetch.service", "ProtectHome") == ["read-only"]
    assert unit_values("pipeline-fetch.service", "ReadWritePaths") == ["%h/.local/share/pipeline"]


def test_timer_runs_every_five_minutes_within_the_collector_tolerance():
    assert unit_values("pipeline-fetch.timer", "OnCalendar") == ["*:0/5"]
    delay = int(unit_values("pipeline-fetch.timer", "RandomizedDelaySec")[0].removesuffix("s"))
    accuracy = int(unit_values("pipeline-fetch.timer", "AccuracySec")[0].removesuffix("s"))
    assert delay + accuracy < DUE_TOLERANCE_SECONDS


def test_empty_capability_set_keeps_a_directive_that_lets_the_service_start():
    # Sin ninguna de estas, CapabilityBoundingSet= impide arrancar un servicio de usuario.
    assert unit_values("pipeline-fetch.service", "CapabilityBoundingSet") == [""]
    enabling = (
        "ProtectSystem",
        "ProtectHome",
        "ReadWritePaths",
        "PrivateTmp",
        "PrivateDevices",
        "ProtectKernelTunables",
        "ProtectKernelLogs",
        "ProtectControlGroups",
    )
    assert any(unit_values("pipeline-fetch.service", name) for name in enabling)
