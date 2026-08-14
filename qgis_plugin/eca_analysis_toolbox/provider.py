"""Processing provider registration for the ECA tools."""

from qgis.core import QgsProcessingProvider

from .algorithms.eca_draft_algorithm import EcaDraftAlgorithm


class EcaProcessingProvider(QgsProcessingProvider):
    def id(self):
        return "eca"

    def name(self):
        return "ECA Analysis Toolbox"

    def longName(self):
        return self.name()

    def loadAlgorithms(self):
        self.addAlgorithm(EcaDraftAlgorithm())
