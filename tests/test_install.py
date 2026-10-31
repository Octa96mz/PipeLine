import json
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).parent.parent
PLUGIN_FILES = ("manifest.json", "Widget.qml", "Model.js", "MarketPanel.qml", "Sparkline.qml")
UNIT_FILES = ("pipeline-fetch.service", "pipeline-fetch.timer")
SHELL_CONFIG = {
    "version": 1,
    "bar": {"layout": {"left": [{"id": "a"}], "center": [], "right": [{"id": "b"}]}},
}

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq no está instalado")


class Sandbox:
    """Repositorio y HOME temporales. `systemctl` y `omarchy` son dobles que solo anotan."""

    def __init__(self, tmp_path, name="repo"):
        self.root = tmp_path / name
        self.home = tmp_path / "home"
        self.bin = tmp_path / "bin"
        self.calls = tmp_path / "calls.log"
        self.home.mkdir()
        self.bin.mkdir()
        for folder in ("scripts", "plugin", "systemd"):
            shutil.copytree(REPOSITORY / folder, self.root / folder)
        for script in ("install.sh", "uninstall.sh"):
            shutil.copy(REPOSITORY / script, self.root)
        venv_bin = self.root / ".venv/bin"
        venv_bin.mkdir(parents=True)
        self.target = venv_bin / "pipeline"
        self.target.write_text('#!/bin/sh\necho "args:$*"\n', encoding="utf-8")
        self.target.chmod(0o755)
        self.fake("systemctl", 'case "$*" in *is-enabled*) [ -e "$ENABLED" ];; esac')
        self.fake("omarchy", "")
        self.enabled = tmp_path / "enabled"
        self.launcher = self.home / ".local/bin/pipeline"
        self.data = self.home / ".local/share/pipeline"
        self.units = self.home / ".config/systemd/user"
        self.plugin = self.home / ".config/omarchy/plugins/pipeline.market"
        self.shell_json = self.home / ".config/omarchy/shell.json"
        self.config = self.home / ".config/pipeline"

    def fake(self, name, body):
        path = self.bin / name
        path.write_text(
            f'#!/bin/sh\necho "{name} $*" >> "$CALLS"\n{body}\nexit_code=$?\nexit $exit_code\n',
            encoding="utf-8",
        )
        path.chmod(0o755)

    def run(self, script, *args, answers="", extra_env=None):
        tools = f"{self.bin}:/usr/bin:/bin"
        return subprocess.run(
            ["/bin/sh", str(self.root / script), *args],
            env={
                "HOME": str(self.home),
                "PATH": tools,
                "CALLS": str(self.calls),
                "ENABLED": str(self.enabled),
                **(extra_env or {}),
            },
            input=answers,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def install(self, answers=""):
        result = self.run("install.sh", answers=answers)
        assert result.returncode == 0, result.stderr
        return result

    def uninstall(self, answers=""):
        result = self.run("uninstall.sh", answers=answers)
        assert result.returncode == 0, result.stderr
        return result

    def called(self):
        return self.calls.read_text(encoding="utf-8") if self.calls.exists() else ""

    def write_shell_json(self, content=None):
        self.shell_json.parent.mkdir(parents=True, exist_ok=True)
        self.shell_json.write_text(json.dumps(content or SHELL_CONFIG, indent=2) + "\n")
        self.shell_json.chmod(0o600)

    def snapshot(self):
        return {
            str(path): (path.read_bytes() if path.is_file() else None)
            for path in sorted(self.home.rglob("*"))
        }


@pytest.fixture
def sandbox(tmp_path):
    return Sandbox(tmp_path)


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_install_creates_everything(sandbox):
    result = sandbox.install()
    assert mode(sandbox.data) == 0o700
    assert mode(sandbox.launcher) == 0o755
    for name in PLUGIN_FILES:
        assert (sandbox.plugin / name).read_bytes() == (sandbox.root / "plugin" / name).read_bytes()
    for name in UNIT_FILES:
        assert (sandbox.units / name).read_bytes() == (sandbox.root / "systemd" / name).read_bytes()
    assert "omarchy restart shell" in result.stdout
    assert f"omarchy plugin validate {sandbox.plugin}" in sandbox.called()
    assert "systemctl --user daemon-reload" in sandbox.called()


def test_launcher_is_only_an_exec_to_the_venv(sandbox):
    sandbox.install()
    target = sandbox.target.resolve()
    assert sandbox.launcher.read_text(encoding="utf-8") == f'#!/bin/sh\nexec {target} "$@"\n'
    run = subprocess.run(
        [str(sandbox.launcher), "json", "--pretty"],
        env={},
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert run.stdout == "args:json --pretty\n"


def test_install_leaves_no_temporary_files(sandbox):
    sandbox.install()
    names = [path.name for path in sandbox.home.rglob("*") if path.name != "pipeline.market"]
    assert not [name for name in names if re.search(r".\.[A-Za-z0-9]{6}$", name)]


def test_timer_is_enabled_only_after_a_yes(sandbox):
    sandbox.install(answers="n\n")
    assert "enable --now" not in sandbox.called()
    sandbox.calls.unlink()
    sandbox.install(answers="s\n")
    assert "systemctl --user enable --now pipeline-fetch.timer" in sandbox.called()


def test_timer_is_not_enabled_without_an_answer(sandbox):
    result = sandbox.install(answers="")
    assert "enable --now" not in sandbox.called()
    assert "Timer sin habilitar" in result.stdout


def test_install_warns_about_calls_before_enabling(sandbox):
    assert "288 llamadas" in sandbox.install().stdout


def test_second_install_changes_nothing_and_asks_nothing(sandbox):
    sandbox.enabled.touch()
    sandbox.install()
    before = sandbox.snapshot()
    sandbox.calls.unlink()
    result = sandbox.install()
    assert sandbox.snapshot() == before
    assert "[s/N]" not in result.stdout
    assert "daemon-reload" not in sandbox.called()
    assert "omarchy restart shell" not in result.stdout


@pytest.mark.parametrize(
    "relative",
    [
        ".local/bin/pipeline",
        ".config/systemd/user/pipeline-fetch.service",
        ".config/omarchy/plugins/pipeline.market/Widget.qml",
    ],
)
def test_existing_different_file_is_kept_unless_confirmed(sandbox, relative):
    sandbox.enabled.touch()
    path = sandbox.home / relative
    path.parent.mkdir(parents=True)
    path.write_text("existing", encoding="utf-8")

    result = sandbox.install(answers="n\n")
    assert path.read_text(encoding="utf-8") == "existing"
    assert "Se conserva" in result.stdout
    assert "existing" in result.stdout

    sandbox.install(answers="s\n")
    assert path.read_text(encoding="utf-8") != "existing"


def test_no_answer_never_overwrites(sandbox):
    sandbox.launcher.parent.mkdir(parents=True)
    sandbox.launcher.write_text("existing", encoding="utf-8")
    sandbox.install(answers="")
    assert sandbox.launcher.read_text(encoding="utf-8") == "existing"


def test_symlink_is_not_followed_when_replacing(sandbox, tmp_path):
    outside = tmp_path / "outside"
    outside.write_text("outside", encoding="utf-8")
    sandbox.launcher.parent.mkdir(parents=True)
    sandbox.launcher.symlink_to(outside)
    sandbox.install(answers="s\n")
    assert outside.read_text(encoding="utf-8") == "outside"
    assert not sandbox.launcher.is_symlink()


def test_install_requires_the_venv(sandbox):
    sandbox.target.unlink()
    before = sandbox.snapshot()
    result = sandbox.run("install.sh")
    assert result.returncode == 1
    assert "python3 -m venv .venv" in result.stdout
    assert sandbox.snapshot() == before


def test_install_refuses_unsafe_repository_paths(tmp_path):
    sandbox = Sandbox(tmp_path, name="repo with space")
    result = sandbox.run("install.sh")
    assert result.returncode == 1
    assert "no admitidos" in result.stderr
    assert not sandbox.launcher.exists()


def test_unknown_option_is_rejected_before_changing_anything(sandbox):
    before = sandbox.snapshot()
    for script in ("install.sh", "uninstall.sh"):
        assert sandbox.run(script, "--force").returncode == 1
    assert sandbox.snapshot() == before


def test_install_dry_run_changes_nothing(sandbox):
    sandbox.write_shell_json()
    before = sandbox.snapshot()
    result = sandbox.run("install.sh", "--dry-run", answers="s\ns\ns\n")
    assert result.returncode == 0, result.stderr
    assert sandbox.snapshot() == before
    assert "Simulación terminada" in result.stdout
    assert f"crearía {sandbox.launcher}" in result.stdout
    assert "[s/N]" not in result.stdout
    for forbidden in ("daemon-reload", "enable --now", "disable", "stop", "validate"):
        assert forbidden not in sandbox.called()


def test_dry_run_never_writes_next_to_shell_json(sandbox):
    # El shell vigila ese fichero: ni siquiera un temporal debe aparecer a su lado.
    sandbox.write_shell_json()
    sandbox.fake("jq", 'ls "$(dirname "$SHELL_JSON")" >> "$CALLS"\nexec /usr/bin/jq "$@"')
    result = sandbox.run(
        "install.sh", "--dry-run", extra_env={"SHELL_JSON": str(sandbox.shell_json)}
    )
    assert result.returncode == 0, result.stderr
    assert not [line for line in sandbox.called().splitlines() if line.startswith("shell.json.")]


def test_install_dry_run_shows_the_shell_json_diff(sandbox):
    sandbox.write_shell_json()
    result = sandbox.run("install.sh", "--dry-run")
    added = [line for line in result.stdout.splitlines() if line.startswith("+")]
    assert any("pipeline.market" in line for line in added)
    assert "preguntaría antes de aplicar" in result.stdout


def test_shell_json_is_not_changed_without_a_yes(sandbox):
    sandbox.enabled.touch()
    sandbox.write_shell_json()
    before = sandbox.shell_json.read_bytes()
    result = sandbox.install(answers="n\n")
    assert sandbox.shell_json.read_bytes() == before
    assert "pipeline.market" in result.stdout
    assert "shell.json no se ha tocado" in result.stdout
    assert not list(sandbox.shell_json.parent.glob("shell.json.*"))


def test_shell_json_change_makes_a_dated_copy_and_keeps_permissions(sandbox):
    sandbox.enabled.touch()
    sandbox.write_shell_json()
    before = sandbox.shell_json.read_bytes()
    sandbox.install(answers="s\n")
    config = json.loads(sandbox.shell_json.read_text())
    assert config["bar"]["layout"]["right"] == [{"id": "b"}, {"id": "pipeline.market"}]
    assert config["bar"]["layout"]["left"] == [{"id": "a"}]
    assert mode(sandbox.shell_json) == 0o600
    backups = list(sandbox.shell_json.parent.glob("shell.json.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == before
    assert not list(sandbox.shell_json.parent.glob("shell.json.??????"))


def test_shell_json_changed_during_the_question_is_not_overwritten(sandbox):
    sandbox.enabled.touch()
    sandbox.write_shell_json()
    process = subprocess.Popen(
        ["/bin/sh", str(sandbox.root / "install.sh")],
        env={
            "HOME": str(sandbox.home),
            "PATH": f"{sandbox.bin}:/usr/bin:/bin",
            "CALLS": str(sandbox.calls),
            "ENABLED": str(sandbox.enabled),
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    seen = ""
    while "[s/N]" not in seen:
        seen += process.stdout.read(1)
    moved = '{"version": 1, "bar": {"layout": {"right": [{"id": "moved"}]}}}\n'
    sandbox.shell_json.write_text(moved, encoding="utf-8")
    output, _ = process.communicate("s\n", timeout=30)
    assert process.returncode == 0
    assert sandbox.shell_json.read_text(encoding="utf-8") == moved
    assert "cambió mientras esperaba" in output
    assert not list(sandbox.shell_json.parent.glob("shell.json.bak.*"))


def test_shell_json_already_listing_the_plugin_is_left_alone(sandbox):
    sandbox.enabled.touch()
    sandbox.write_shell_json(
        {"version": 1, "bar": {"layout": {"center": [{"id": "pipeline.market"}]}}}
    )
    before = sandbox.shell_json.read_bytes()
    result = sandbox.install()
    assert sandbox.shell_json.read_bytes() == before
    assert "ya incluye" in result.stdout


def test_invalid_shell_json_is_never_touched(sandbox):
    sandbox.enabled.touch()
    sandbox.shell_json.parent.mkdir(parents=True)
    sandbox.shell_json.write_text("{ broken", encoding="utf-8")
    result = sandbox.install(answers="s\n")
    assert sandbox.shell_json.read_text(encoding="utf-8") == "{ broken"
    assert "no es JSON válido" in result.stdout


def test_missing_shell_json_is_not_created(sandbox):
    sandbox.enabled.touch()
    result = sandbox.install()
    assert not sandbox.shell_json.exists()
    assert "bar.layout" in result.stdout


def test_scripts_never_use_plugin_enable_or_sudo():
    for name in ("install.sh", "uninstall.sh", "scripts/common.sh"):
        lines = (REPOSITORY / name).read_text(encoding="utf-8").splitlines()
        code = [line for line in lines if not line.lstrip().startswith("#")]
        for forbidden in ("omarchy plugin enable", "sudo ", "/etc/", "/home/"):
            assert not [line for line in code if forbidden in line and "con sudo" not in line]


def test_uninstall_removes_what_install_created_but_keeps_data_and_config(sandbox):
    sandbox.enabled.touch()
    sandbox.install()
    sandbox.data.joinpath("pipeline.db").write_text("synthetic")
    sandbox.config.mkdir()
    sandbox.config.joinpath("secrets.toml").write_text("synthetic")
    sandbox.calls.unlink()

    result = sandbox.uninstall(answers="n\nn\n")

    assert "systemctl --user disable --now pipeline-fetch.timer" in sandbox.called()
    assert "systemctl --user daemon-reload" in sandbox.called()
    assert not sandbox.launcher.exists()
    assert not sandbox.plugin.exists()
    for name in UNIT_FILES:
        assert not (sandbox.units / name).exists()
    assert sandbox.data.joinpath("pipeline.db").exists()
    assert sandbox.config.joinpath("secrets.toml").exists()
    assert "omarchy restart shell" in result.stdout


def test_uninstall_without_answers_keeps_data_and_config(sandbox):
    sandbox.install()
    sandbox.data.joinpath("pipeline.db").write_text("synthetic")
    sandbox.config.mkdir()
    sandbox.uninstall(answers="")
    assert sandbox.data.joinpath("pipeline.db").exists()
    assert sandbox.config.exists()


@pytest.mark.parametrize(
    ("answers", "data_kept", "config_kept"),
    [("s\nn\n", False, True), ("n\ns\n", True, False), ("s\ns\n", False, False)],
)
def test_uninstall_asks_separately_for_data_and_config(sandbox, answers, data_kept, config_kept):
    sandbox.install()
    sandbox.config.mkdir()
    sandbox.uninstall(answers=answers)
    assert sandbox.data.exists() is data_kept
    assert sandbox.config.exists() is config_kept


def test_uninstall_questions_name_the_keys(sandbox):
    sandbox.install()
    sandbox.config.mkdir()
    assert "la configuración y las claves" in sandbox.uninstall(answers="n\nn\n").stdout


def test_uninstall_keeps_modified_files_unless_confirmed(sandbox):
    sandbox.install()
    changed = sandbox.plugin / "Widget.qml"
    changed.write_text("modified", encoding="utf-8")
    sandbox.launcher.write_text("modified", encoding="utf-8")

    result = sandbox.uninstall(answers="n\nn\nn\nn\n")
    assert changed.read_text(encoding="utf-8") == "modified"
    assert sandbox.launcher.read_text(encoding="utf-8") == "modified"
    assert "aún contiene ficheros" in result.stdout

    sandbox.uninstall(answers="s\ns\nn\nn\n")
    assert not changed.exists()
    assert not sandbox.launcher.exists()


def test_uninstall_keeps_files_it_did_not_install(sandbox):
    sandbox.install()
    extra = sandbox.plugin / "notes.txt"
    extra.write_text("mine", encoding="utf-8")
    result = sandbox.uninstall()
    assert extra.read_text(encoding="utf-8") == "mine"
    assert "aún contiene ficheros" in result.stdout


def test_uninstall_removes_the_bar_entry_only_after_a_yes(sandbox):
    sandbox.enabled.touch()
    sandbox.write_shell_json()
    sandbox.install(answers="s\n")
    with_entry = sandbox.shell_json.read_bytes()

    sandbox.uninstall(answers="n\n")
    assert sandbox.shell_json.read_bytes() == with_entry

    sandbox.install()
    sandbox.uninstall(answers="s\n")
    config = json.loads(sandbox.shell_json.read_text())
    assert config["bar"]["layout"]["right"] == [{"id": "b"}]
    assert mode(sandbox.shell_json) == 0o600


def test_backups_made_within_the_same_second_never_overwrite_each_other(sandbox):
    sandbox.enabled.touch()
    sandbox.write_shell_json()
    original = sandbox.shell_json.read_bytes()
    sandbox.fake("date", "echo 20300101-000000")
    sandbox.install(answers="s\n")
    with_entry = sandbox.shell_json.read_bytes()
    sandbox.uninstall(answers="s\n")
    backups = sorted(sandbox.shell_json.parent.glob("shell.json.bak.*"))
    assert [path.name for path in backups] == [
        "shell.json.bak.20300101-000000",
        "shell.json.bak.20300101-000000.1",
    ]
    assert backups[0].read_bytes() == original
    assert backups[1].read_bytes() == with_entry


def test_uninstall_dry_run_changes_nothing(sandbox):
    sandbox.enabled.touch()
    sandbox.write_shell_json()
    sandbox.install(answers="s\n")
    sandbox.config.mkdir()
    before = sandbox.snapshot()
    sandbox.calls.unlink()
    result = sandbox.run("uninstall.sh", "--dry-run", answers="s\ns\ns\n")
    assert result.returncode == 0, result.stderr
    assert sandbox.snapshot() == before
    assert sandbox.called() == ""
    assert "Simulación terminada" in result.stdout
    assert "[s/N]" not in result.stdout
    assert f"preguntaría antes de borrar {sandbox.data}" in result.stdout


def test_uninstall_with_nothing_installed_succeeds(sandbox):
    assert sandbox.run("uninstall.sh").returncode == 0
    assert sandbox.called() == ""


def test_uninstall_never_follows_a_symlinked_directory(sandbox, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    outside.joinpath("keep").write_text("keep", encoding="utf-8")
    sandbox.data.parent.mkdir(parents=True)
    sandbox.data.symlink_to(outside)
    result = sandbox.run("uninstall.sh", answers="s\ns\n")
    assert result.returncode == 0
    assert outside.joinpath("keep").exists()
    assert "enlace simbólico" in result.stdout


def test_install_then_uninstall_leaves_only_empty_parents(sandbox):
    sandbox.install()
    sandbox.uninstall(answers="s\n")
    files = [path for path in sandbox.home.rglob("*") if path.is_file()]
    assert files == []
