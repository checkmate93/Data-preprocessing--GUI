"""Reusable pydantic fields with UI hints for the React form generator.

json_schema_extra keys the frontend understands:
- ui: "columns" (multi column picker), "column" (single picker; optional when not in `required`),
  "rename_map", "conditions", "multienum", "aggregations", "attachment" (second uploaded file), "json"
- enum_labels: {value: Greek label} for select boxes
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def columns_field(title="Στήλες", description="Άφησέ το κενό για όλες τις κατάλληλες στήλες", required=False):
    return Field(
        default_factory=list,
        title=title,
        description=None if required else description,
        json_schema_extra={"ui": "columns", "required_choice": required},
    )


def column_field(title="Στήλη"):
    return Field(title=title, json_schema_extra={"ui": "column"})


def choice(default, title, labels, description=None):
    return Field(default=default, title=title, description=description, json_schema_extra={"enum_labels": labels})


def optional_column_field(title="Στήλη", description=None):
    """Single column picker with a '— καμία —' option (empty string = none)."""
    return Field("", title=title, description=description, json_schema_extra={"ui": "column"})


def attachment_field(title="Δεύτερο αρχείο"):
    return Field(title=title, description="Ανέβασέ το από εδώ· μένει στη συνεδρία για επόμενες χρήσεις.",
                 json_schema_extra={"ui": "attachment"})


def json_field(title, description=None):
    return Field("", title=title, description=description, json_schema_extra={"ui": "json"})


AGG_LABELS = {
    "sum": "Άθροισμα", "mean": "Μέσος όρος", "median": "Διάμεσος", "min": "Ελάχιστο", "max": "Μέγιστο",
    "count": "Πλήθος (μη κενά)", "nunique": "Μοναδικές τιμές", "first": "Πρώτη", "last": "Τελευταία", "std": "Τυπ. απόκλιση",
}


class Aggregation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    func: Literal["sum", "mean", "median", "min", "max", "count", "nunique", "first", "last", "std"]


def aggregations_field():
    return Field(default_factory=list, title="Συναθροίσεις", min_length=1,
                 json_schema_extra={"ui": "aggregations", "agg_labels": AGG_LABELS})
