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


def test_repository_has_no_personal_paths():
    checked = [REPOSITORY / name for name in ("src", "plugin", "scripts", "docs", "systemd")]
    files = [path for folder in checked for path in folder.rglob("*") if path.is_file()]
    files += [
        REPOSITORY / name
        for name in (
            "README.md",
            "config.example.toml",
            "pyproject.toml",
            "install.sh",
            "uninstall.sh",
        )
    ]
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


def report_with(tmp_path, *rows, status="fresh"):
    return {
        "schema_version": 1,
        "status": status,
        "bar": {"items": [], "tooltip": ""},
        "groups": [
            {"title": "Cripto", "series_label": "7 d", "change_label": "24 h", "items": list(rows)},
            {
                "title": "Índices",
                "series_label": None,
                "change_label": None,
                "items": [
                    {
                        "name": "S&P 500",
                        "state": "unavailable",
                        "reason": "Sin proveedor configurado",
                    },
                    {
                        "name": "IBEX 35",
                        "state": "unavailable",
                        "reason": "Sin proveedor configurado",
                    },
                ],
            },
        ],
        "providers": [
            {
                "attribution": "Powered by CoinGecko",
                "calls_24h": 3,
                "last_attempt": {"age_text": "hace 1 min", "outcome_label": "correcto"},
                "cooldown_until_text": None,
                "offline_streak": 0,
                "next_attempt_text": None,
            }
        ],
    }


def row(**overrides):
    values = {
        "symbol": "BTC",
        "name": "Bitcoin",
        "state": "fresh",
        "state_label": "hace 1 min",
        "reason": None,
        "price": 1000.0,
        "price_text": "1000,00 $",
        "change_text": "+1,50 %",
        "direction": "up",
        "age_text": "hace 1 min",
        "series": [1.0, 2.0],
    }
    return {**values, **overrides}


def fresh(tmp_path, *rows, status="fresh"):
    return {"report": report_with(tmp_path, *rows, status=status), "failed": False, "message": ""}


@needs_node
def test_panel_row_has_every_requested_field(tmp_path):
    group = model("panelGroups", fresh(tmp_path, row()))[0]
    assert (group["title"], group["seriesLabel"], group["changeLabel"]) == ("Cripto", "7 d", "24 h")
    assert group["rows"][0] == {
        "symbol": "BTC",
        "name": "Bitcoin",
        "priceText": "1000,00 $",
        "changeText": "+1,50 %",
        "role": "up",
        "stateText": "hace 1 min",
        "note": "",
        "series": [1.0, 2.0],
    }


@needs_node
def test_group_without_provider_collapses_to_one_line(tmp_path):
    group = model("panelGroups", fresh(tmp_path, row()))[1]
    assert group["rows"] == []
    assert group["summary"] == "S&P 500, IBEX 35 · sin proveedor configurado"
    assert group["seriesLabel"] == ""


@needs_node
@pytest.mark.parametrize(
    ("state", "direction", "role", "text"),
    [
        ("stale", "up", "stale", "obsoleto · hace 1 min"),
        ("held", "up", "held", "retenido · hace 1 min"),
    ],
)
def test_data_age_stays_visible_when_not_fresh(tmp_path, state, direction, role, text):
    item = row(state=state, direction=direction, reason="Motivo")
    panel_row = model("panelGroups", fresh(tmp_path, item, status="stale"))[0]["rows"][0]
    assert panel_row["role"] == role
    assert panel_row["stateText"] == text


@needs_node
def test_only_held_rows_carry_their_reason(tmp_path):
    held = row(state="held", reason="Retenido: salto del 200 %")
    stale = row(symbol="ETH", state="stale", reason="Sin conexión")
    rows = model("panelGroups", fresh(tmp_path, held, stale, status="stale"))[0]["rows"]
    assert rows[0]["note"] == "Retenido: salto del 200 %"
    assert rows[1]["note"] == ""


@needs_node
def test_row_without_price_shows_a_dash(tmp_path):
    item = row(
        state="no_data",
        state_label="sin datos",
        reason="Más de 24 h sin refresco",
        price=None,
        price_text=None,
        change_text=None,
        direction=None,
        age_text=None,
        series=[],
    )
    panel_row = model("panelGroups", fresh(tmp_path, item, status="no_data"))[0]["rows"][0]
    assert panel_row["priceText"] == "—"
    assert panel_row["changeText"] == "—"
    assert panel_row["role"] == "none"
    assert panel_row["stateText"] == "sin datos"


@needs_node
def test_failed_read_shows_saved_rows_as_stale(tmp_path):
    result = {"report": report_with(tmp_path, row()), "failed": True, "message": "sin respuesta"}
    panel_row = model("panelGroups", result)[0]["rows"][0]
    assert panel_row["role"] == "stale"
    assert panel_row["stateText"] == "obsoleto · hace 1 min"
    assert model("banner", result) == "No se pudo actualizar: sin respuesta"


@needs_node
def test_banner_explains_stale_data_without_repeating_reasons(tmp_path):
    rows = [
        row(state="stale", reason="Sin conexión"),
        row(symbol="ETH", state="stale", reason="Sin conexión"),
        row(symbol="XRP", state="held", reason="Retenido"),
    ]
    assert (
        model("banner", fresh(tmp_path, *rows, status="stale")) == "Datos obsoletos: Sin conexión"
    )


@needs_node
def test_banner_is_empty_for_fresh_data_and_explains_missing_data(tmp_path):
    assert model("banner", fresh(tmp_path, row())) == ""
    assert model("banner", fresh(tmp_path, status="no_data")) == "Todavía no hay datos."
    assert model("banner", None) == "Cargando…"


@needs_node
def test_footer_has_attribution_calls_and_last_attempt(tmp_path):
    lines = model("footerLines", fresh(tmp_path, row()))
    assert lines == [
        "Powered by CoinGecko · llamadas (24 h): 3 · último intento hace 1 min, correcto"
    ]


@needs_node
def test_footer_reports_pause_and_backoff(tmp_path):
    result = fresh(tmp_path, row())
    result["report"]["providers"][0].update(
        cooldown_until_text="15:00", offline_streak=3, next_attempt_text="15:10"
    )
    lines = model("footerLines", result)
    assert "En pausa por el proveedor hasta las 15:00" in lines
    assert "Sin conexión en 3 pasadas seguidas; próximo intento hacia las 15:10" in lines


@needs_node
def test_refresh_button_states(tmp_path):
    result = fresh(tmp_path, row())
    assert model("refreshState", result, "idle") == {
        "enabled": True,
        "label": "Actualizar",
        "note": "",
    }
    requested = model("refreshState", result, "requested")
    assert requested["enabled"] is False
    assert "solo llama" in requested["note"]
    failed = model("refreshState", result, "failed")
    assert failed["enabled"] is True
    assert "timer" in failed["note"]


@needs_node
def test_refresh_button_is_disabled_during_a_pause(tmp_path):
    result = fresh(tmp_path, row())
    result["report"]["providers"][0]["cooldown_until_text"] = "15:00"
    state = model("refreshState", result, "idle")
    assert state["enabled"] is False
    assert "15:00" in state["label"]


@needs_node
def test_sparkline_points_fill_the_area_with_high_values_on_top():
    points = model("sparklinePoints", [1.0, 3.0, 2.0], 102, 22, 1)
    assert points == [{"x": 1, "y": 21}, {"x": 51, "y": 1}, {"x": 101, "y": 11}]


@needs_node
def test_flat_sparkline_is_a_centred_line():
    points = model("sparklinePoints", [5.0, 5.0], 12, 12, 1)
    assert [point["y"] for point in points] == [6, 6]


@needs_node
@pytest.mark.parametrize("values", [[], [1.0], None])
def test_sparkline_needs_two_points(values):
    assert model("sparklinePoints", values, 100, 20, 1) == []


@needs_node
def test_panel_reads_a_real_report(tmp_path):
    report = real_report(tmp_path)
    result = model("parseReport", json.dumps(report), None)
    groups = model("panelGroups", result)
    assert [group["title"] for group in groups] == ["Cripto", "Índices", "Acciones"]
    assert groups[0]["seriesLabel"] == "7 d"
    assert groups[0]["changeLabel"] == "24 h"
    assert len(groups[0]["rows"]) == 4
    assert groups[1]["rows"] == []
    assert "S&P 500" in groups[1]["summary"]
    assert model("footerLines", result)[0].startswith("Powered by CoinGecko")


def test_panel_files_never_contact_a_provider():
    for name in ("Widget.qml", "MarketPanel.qml", "Sparkline.qml", "Model.js"):
        source = (PLUGIN / name).read_text(encoding="utf-8")
        for forbidden in ("https://", "http://", "XMLHttpRequest", "curl", "bash"):
            assert forbidden not in source, (name, forbidden)


def test_refresh_only_starts_the_collector_service():
    source = (PLUGIN / "Widget.qml").read_text(encoding="utf-8")
    assert (
        'command: ["systemctl", "--user", "start", "--no-block", "pipeline-fetch.service"]'
        in source
    )
    assert '"fetch"' not in source


def test_sparkline_has_no_variation_colours():
    source = (PLUGIN / "Sparkline.qml").read_text(encoding="utf-8")
    assert "#9ece6a" not in source
    assert "#f7768e" not in source
    panel = (PLUGIN / "MarketPanel.qml").read_text(encoding="utf-8")
    assert "lineColor: panel.textColor" in panel


@needs_node
@pytest.mark.parametrize(
    "report",
    [
        {"schema_version": 1, "status": "fresh"},
        {"schema_version": 1, "status": "fresh", "bar": {"items": []}, "providers": []},
        {
            "schema_version": 1,
            "status": "fresh",
            "bar": {"items": []},
            "providers": [],
            "groups": [{"title": "Sin items"}],
        },
    ],
)
def test_same_version_with_missing_fields_keeps_the_previous_report(report):
    previous = {"schema_version": 1, "bar": {"items": [], "tooltip": "Anterior"}, "groups": []}
    result = model("parseReport", json.dumps(report), previous)
    assert result["failed"] is True
    assert result["message"] == "datos incompletos"
    assert result["report"] == previous
    assert model("panelGroups", result) == []
