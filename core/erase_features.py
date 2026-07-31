"""
Erase analysis workaround for users without an Advanced ArcGIS license.

Uses Union + FID filtering to replicate the Erase tool behaviour.
Updated for ArcGIS Pro (no arcpy.mapping dependency).
"""

import arcpy
import os


class EraseFeatures:
    """Perform an erase operation using Union instead of the licensed Erase tool."""

    def __init__(self, in_features, erase_features, out_features):
        self.input_features = in_features
        self.erase_features = erase_features
        self.output_features = out_features
        self.workspace = "memory"
        arcpy.env.overwriteOutput = True

    def erase_analysis(self):
        """Run the erase and write results to *self.output_features*."""
        erase_type = arcpy.Describe(self.input_features).shapeType

        str_name = arcpy.Describe(self.erase_features).name
        str_name_split = str_name.split(".")
        if len(str_name_split) > 1:
            str_name = str_name_split[1]
            if str_name == "shp":
                str_name = str_name_split[0]
        else:
            str_name = str_name_split[0]

        fld_fid = f"FID_{str_name}"

        lst_keep_fields = (
            [f.name for f in arcpy.ListFields(self.input_features)]
            + ["Shape_Area", "Shape_Length", "OBJECTID"]
        )

        if erase_type == "Polygon":
            output = self._erase_polygon(self.input_features, self.erase_features)
        else:
            input_mbg = os.path.join(self.workspace, "input_mbg")
            intersect = os.path.join(self.workspace, "intersect")

            arcpy.MinimumBoundingGeometry_management(
                in_features=self.input_features,
                out_feature_class=input_mbg,
                geometry_type="ENVELOPE",
                group_option="ALL",
            )
            union = self._erase_polygon(input_mbg, self.erase_features)
            arcpy.Intersect_analysis(
                in_features=[self.input_features, union],
                out_feature_class=intersect,
                join_attributes="ALL",
            )
            output = intersect

        with arcpy.da.UpdateCursor(output, fld_fid) as cursor:
            for row in cursor:
                if row[0] != -1:
                    cursor.deleteRow()

        lst_delete = [
            f.name for f in arcpy.ListFields(output)
            if f.name not in lst_keep_fields
        ]
        if lst_delete:
            arcpy.DeleteField_management(output, lst_delete)

        arcpy.CopyFeatures_management(output, self.output_features)

    def _erase_polygon(self, input_features, erase_features):
        """Union two polygon layers and return the union path."""
        union = os.path.join(self.workspace, "union")
        arcpy.Union_analysis(
            in_features=[input_features, erase_features],
            out_feature_class=union,
            join_attributes="ALL",
            gaps="GAPS",
        )
        return union
