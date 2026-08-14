"""QGIS Processing algorithm for the review-ready ECA draft workflow."""

from __future__ import annotations

from pathlib import Path
import sys

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputFile,
    QgsProcessingOutputFolder,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterString,
)


def _import_engine():
    """Import the vendored engine in a release zip or the repo engine in development."""
    plugin_dir = Path(__file__).resolve().parents[1]
    repository_root = Path(__file__).resolve().parents[3]
    for candidate in (plugin_dir, repository_root):
        if (candidate / "open_eca").is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    try:
        # QGIS may set PROJ_LIB for its bundled GDAL.  When a newer pyproj is
        # installed in the user site, it needs to use the matching proj.db
        # shipped with that package instead of QGIS's older database.
        import pyproj

        pyproj_data = Path(pyproj.__file__).resolve().parent / "proj_dir" / "share" / "proj"
        if (pyproj_data / "proj.db").is_file():
            pyproj.datadir.set_data_dir(str(pyproj_data))
        from open_eca.draft import run_draft
        from open_eca.recovery import load_curves
    except ImportError as error:
        raise QgsProcessingException(
            "The ECA engine is missing. Install the plugin from the release ZIP, "
            "or run it from the ECA project checkout."
        ) from error
    return run_draft, load_curves


class EcaDraftAlgorithm(QgsProcessingAlgorithm):
    """Build an editable ECA draft GeoPackage and supporting reports."""

    WATERSHED = "WATERSHED"
    BASIN_FIELD = "BASIN_FIELD"
    SUBBASIN_FIELD = "SUBBASIN_FIELD"
    INPUTS = "INPUTS"
    DEM = "DEM"
    CURVES = "CURVES"
    FIELD_TEAM = "FIELD_TEAM"
    OUTPUT = "OUTPUT"
    DRAFT_GPKG = "DRAFT_GPKG"
    REPORTS = "REPORTS"

    def name(self):
        return "eca_draft"

    def displayName(self):
        return "Create ECA Draft"

    def group(self):
        return "ECA workflow"

    def groupId(self):
        return "eca_workflow"

    def shortHelpString(self):
        return (
            "Runs the ECA estimate workflow with local, reproducible inputs. "
            "The output folder must be new or empty. The resulting GeoPackage contains "
            "an editable openings layer for analyst QA/QC."
        )

    def createInstance(self):
        return EcaDraftAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.WATERSHED, "Watershed or sub-basin polygons",
            fileFilter="Vector files (*.gpkg *.geojson *.shp)",
        ))
        self.addParameter(QgsProcessingParameterString(self.BASIN_FIELD, "Basin-name field"))
        self.addParameter(QgsProcessingParameterString(self.SUBBASIN_FIELD, "Sub-basin-name field"))
        self.addParameter(QgsProcessingParameterFile(
            self.INPUTS, "Catalogue cache GeoPackage", fileFilter="GeoPackage (*.gpkg)",
        ))
        self.addParameter(QgsProcessingParameterFile(
            self.DEM, "DEM GeoTIFF", fileFilter="GeoTIFF (*.tif *.tiff)",
        ))
        self.addParameter(QgsProcessingParameterFile(
            self.CURVES, "Recovery curves workbook", fileFilter="Excel workbook (*.xlsx)",
        ))
        field_team = QgsProcessingParameterString(self.FIELD_TEAM, "Field team (optional)", optional=True)
        self.addParameter(field_team)
        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUTPUT, "New or empty draft output folder",
        ))
        self.addOutput(QgsProcessingOutputFile(self.DRAFT_GPKG, "ECA Draft GeoPackage"))
        self.addOutput(QgsProcessingOutputFolder(self.REPORTS, "Summary reports"))

    def processAlgorithm(self, parameters, context, feedback):
        run_draft, load_curves = _import_engine()
        output_dir = Path(self.parameterAsString(parameters, self.OUTPUT, context))
        try:
            result = run_draft(
                Path(self.parameterAsFile(parameters, self.WATERSHED, context)),
                self.parameterAsString(parameters, self.BASIN_FIELD, context),
                self.parameterAsString(parameters, self.SUBBASIN_FIELD, context),
                Path(self.parameterAsFile(parameters, self.INPUTS, context)),
                Path(self.parameterAsFile(parameters, self.DEM, context)),
                load_curves(Path(self.parameterAsFile(parameters, self.CURVES, context))),
                output_dir,
                self.parameterAsString(parameters, self.FIELD_TEAM, context) or None,
            )
        except Exception as error:
            raise QgsProcessingException(str(error)) from error

        feedback.pushInfo(f"ECA draft GeoPackage: {result.geopackage}")
        feedback.pushInfo(f"Reports: {result.report_dir}")
        return {
            self.OUTPUT: str(output_dir),
            self.DRAFT_GPKG: str(result.geopackage),
            self.REPORTS: str(result.report_dir),
        }
