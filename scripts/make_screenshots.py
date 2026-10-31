"""Genera las capturas del README con datos inventados, sin red y sin tocar el escritorio.

Dibuja plugin/MarketPanel.qml real en una instancia aparte de Quickshell, con la plataforma
offscreen, y guarda solo ese elemento. Uso: .venv/bin/python scripts/make_screenshots.py
"""

import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parent.parent
OUTPUT = REPOSITORY / "docs/screenshots"
HARNESS = OUTPUT / "harness"
PLUGIN_FILES = ("MarketPanel.qml", "Sparkline.qml", "Model.js")

# Cifras redondas e inventadas a propósito: no deben confundirse con precios reales.
COINS = (
    ("BTC", 50000.0, 2.0, 0.0),
    ("ETH", 2000.0, -1.0, 1.5),
    ("XRP", 1.0, 3.0, 3.0),
    ("NEAR", 5.0, -2.0, 4.5),
)


def _series(price, phase, now):
    return [
        (now - (47 - step) * 3600, price * (1 + 0.04 * math.sin(step / 5 + phase) + step * 0.0005))
        for step in range(48)
    ]


def _report(folder, now, degraded):
    # Los módulos leen estas variables al usarse: nada apunta a los datos del usuario.
    os.environ["XDG_DATA_HOME"] = str(folder / "data")
    os.environ["XDG_CONFIG_HOME"] = str(folder / "config")
    from pipeline.config import Config
    from pipeline.db import Database, Quote
    from pipeline.paths import database_path
    from pipeline.report import build_report

    path = database_path()
    path.unlink(missing_ok=True)
    age = 900 if degraded else 120
    with Database.open(path) as database:
        for symbol, price, change, phase in COINS:
            quote = Quote(
                symbol, "crypto", "coingecko", price, "USD", change, "live", now - age, now - age
            )
            database.save_snapshot(quote, _series(price, phase, now - age))
        database.record_api_call("coingecko", now - age)
        database.record_attempt("coingecko", now - age, "ok")
        if degraded:
            database.hold_quote("ETH", 6000.0, 200.0, now - 300)
            database.record_attempt("coingecko", now - 60, "offline", "Sin conexión")
        return json.dumps(build_report(Config(), database, now), ensure_ascii=False)


def main() -> int:
    if not shutil.which("quickshell"):
        print("Falta quickshell")
        return 1
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        root = folder / "root"
        shutil.copytree(HARNESS, root)
        (root / "plugin").mkdir()
        for name in PLUGIN_FILES:
            shutil.copy(REPOSITORY / "plugin" / name, root / "plugin" / name)

        now = int(time.time())
        data = (
            f"var outputDir = {json.dumps(str(folder))};\n"
            f"var normal = {json.dumps(_report(folder, now, False))};\n"
            f"var degraded = {json.dumps(_report(folder, now, True))};\n"
        )
        (root / "data.js").write_text(data, encoding="utf-8")

        environment = {
            "PATH": os.environ["PATH"],
            "HOME": str(folder / "home"),
            "XDG_RUNTIME_DIR": str(folder),
            "XDG_CONFIG_HOME": str(folder / "config"),
            "XDG_CACHE_HOME": str(folder / "cache"),
            "XDG_DATA_HOME": str(folder / "data"),
            "XDG_STATE_HOME": str(folder / "state"),
            "QT_QPA_PLATFORM": "offscreen",
            "QT_QUICK_BACKEND": "software",
        }
        result = subprocess.run(  # noqa: S603
            ["quickshell", "-p", str(root / "shell.qml")],  # noqa: S607
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        output = (result.stdout + result.stderr).replace(str(folder), "<tmp>")
        print(output[-1500:])
        names = ("panel.png", "panel-stale.png")
        if not all((folder / name).exists() for name in names):
            print("No se generaron las imágenes")
            return 1
        for name in names:
            shutil.copy(folder / name, OUTPUT / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
