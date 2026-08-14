"""QGIS Processing wrapper for the Open ECA draft workflow.

Copy this file into a QGIS Processing scripts folder, then run it from the
Toolbox. It calls the same tested workflow as the command-line interface.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qgis.core import (  # type: ignore[import-not-found]
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterString,
)

from open_eca.draft import run_draft
from open_eca.recovery import load_curves


class EcaDraftAlgorithm(QgsProcessingAlgorithm):
    WATERSHED = "WATERSHED"
    BASIN_FIELD = "BASIN_FIELD"
    SUBBASIN_FIELD = "SUBBASIN_FIELD"
    INPUTS = "INPUTS"
    DEM = "DEM"
    CURVES = "CURVES"
    FIELD_TEAM = "FIELD_TEAM"
    OUTPUT = "OUTPUT"

    def name(self):
        return "eca_draft"

    def displayName(self):
        return "ECA Draft (Open Source)"

    def group(self):
        return "Open ECA"

    def groupId(self):
        return "open_eca"

    def createInstance(self):
        return EcaDraftAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(self.WATERSHED, "Watershed input", extension="gpkg"))
        self.addParameter(QgsProcessingParameterString(self.BASIN_FIELD, "Basin-name field"))
        self.addParameter(QgsProcessingParameterString(self.SUBBASIN_FIELD, "Sub-basin-name field"))
        self.addParameter(QgsProcessingParameterFile(self.INPUTS, "Catalogue cache GeoPackage", extension="gpkg"))
        self.addParameter(QgsProcessingParameterFile(self.DEM, "DEM GeoTIFF", extension="tif"))
        self.addParameter(QgsProcessingParameterFile(self.CURVES, "Recovery curves workbook", extension="xlsx"))
        self.addParameter(QgsProcessingParameterString(self.FIELD_TEAM, "Field team", optional=True))
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUTPUT, "Draft output folder"))

    def processAlgorithm(self, parameters, context, feedback):
        try:
            result = run_draft(
                Path(self.parameterAsFile(parameters, self.WATERSHED, context)),
                self.parameterAsString(parameters, self.BASIN_FIELD, context),
                self.parameterAsString(parameters, self.SUBBASIN_FIELD, context),
                Path(self.parameterAsFile(parameters, self.INPUTS, context)),
                Path(self.parameterAsFile(parameters, self.DEM, context)),
                load_curves(Path(self.parameterAsFile(parameters, self.CURVES, context))),
                Path(self.parameterAsString(parameters, self.OUTPUT, context)),
                self.parameterAsString(parameters, self.FIELD_TEAM, context) or None,
            )
        except Exception as error:
            raise QgsProcessingException(str(error)) from error
        feedback.pushInfo(f"Draft output: {result.geopackage}")
        return {self.OUTPUT: str(result.geopackage)}
