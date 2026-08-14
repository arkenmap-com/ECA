"""QGIS entry point for the ECA Analysis Toolbox."""


def classFactory(iface):
    from .plugin import EcaAnalysisToolboxPlugin

    return EcaAnalysisToolboxPlugin(iface)
