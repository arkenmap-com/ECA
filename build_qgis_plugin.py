"""Build an installable QGIS plugin ZIP with the Open ECA engine vendored in."""

from __future__ import annotations

import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
PLUGIN_NAME = "eca_analysis_toolbox"
SOURCE_PLUGIN = ROOT / "qgis_plugin" / PLUGIN_NAME
SOURCE_ENGINE = ROOT / "open_eca"
DISTINATION = ROOT / "dist" / f"{PLUGIN_NAME}.zip"


def _ignore(_: str, names: list[str]) -> set[str]:
    return {
        name for name in names
        if name in {"__pycache__", ".DS_Store"} or name.endswith((".pyc", ".pyo"))
    }


def build() -> Path:
    if not SOURCE_PLUGIN.is_dir() or not SOURCE_ENGINE.is_dir():
        raise FileNotFoundError("Run this script from an ECA project checkout with qgis_plugin and open_eca.")
    DISTINATION.parent.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="eca-qgis-plugin-") as temporary:
        staging_root = Path(temporary) / PLUGIN_NAME
        shutil.copytree(SOURCE_PLUGIN, staging_root, ignore=_ignore)
        shutil.copytree(SOURCE_ENGINE, staging_root / "open_eca", ignore=_ignore)
        with ZipFile(DISTINATION, "w", ZIP_DEFLATED) as archive:
            for path in sorted(staging_root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staging_root.parent))
    return DISTINATION


if __name__ == "__main__":
    print(build())
