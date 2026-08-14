"""QGIS plugin lifecycle hooks."""

from pathlib import Path

from qgis.core import QgsApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .provider import EcaProcessingProvider


class EcaAnalysisToolboxPlugin:
    """Registers the ECA Processing provider when QGIS loads the plugin."""

    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.draft_action = None

    def initGui(self):
        self.provider = EcaProcessingProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)
        self._add_toolbar_action()

    def _add_toolbar_action(self):
        icon_path = Path(__file__).resolve().parent / "icons" / "eca_toolbox.svg"
        self.draft_action = QAction(QIcon(str(icon_path)), "Create ECA Draft", self.iface.mainWindow())
        self.draft_action.setObjectName("ecaCreateDraftAction")
        self.draft_action.setStatusTip("Open the Create ECA Draft workflow")
        self.draft_action.triggered.connect(self._open_draft_dialog)
        self.iface.addToolBarIcon(self.draft_action)
        self.iface.addPluginToMenu("&ECA Analysis Toolbox", self.draft_action)

    def _open_draft_dialog(self):
        import processing

        processing.execAlgorithmDialog("eca:eca_draft", {})

    def unload(self):
        if self.draft_action is not None:
            self.iface.removeToolBarIcon(self.draft_action)
            self.iface.removePluginMenu("&ECA Analysis Toolbox", self.draft_action)
            self.draft_action = None
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
