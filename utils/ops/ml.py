"""ML Prep: the v1 leakage-free pipeline as two buttons.

The current dataset version is NOT changed. The button writes train/test files into the session
folder and returns download links. Every statistic (median, mode, IQR bounds, scaler) is fit on
the train split only, then applied to the test split.
"""

import json
from pathlib import Path

from pydantic import Field
from sklearn.model_selection import train_test_split

from utils.artifact_exporter import export_artifacts
from utils.encode_scale_ops import fit_apply_encoding_and_scaling
from utils.op_registry import OpOutput, Params, cards, downloads, operation, require_columns, table, text
from utils.ops.fields import json_field, optional_column_field
from utils.pandas_profiler import profile_dataframe
from utils.schema_advisor import suggest_cleaning_config
from utils.stat_transformers import fit_apply_imputation_and_outliers
from utils.structural_ops import apply_structural_cleaning, to_snake

ML_FOLDER = ("exports", "ml")
ML_FILES = ("train_clean.csv", "test_clean.csv", "preprocess.py", "raw.csv", "config.json")


class SuggestParams(Params):
    target: str = optional_column_field("Στήλη-στόχος (y)", "Κενό = χωρίς στόχο")


class PrepParams(SuggestParams):
    test_size: float = Field(0.2, ge=0, le=0.5, title="Ποσοστό test (0 = χωρίς split)")
    random_state: int = Field(42, title="Random seed")
    config_json: str = json_field(
        "Κανόνες (JSON, προαιρετικό)",
        "Κενό = αυτόματοι κανόνες. Πάρε τους από «Πρόταση κανόνων ML», άλλαξέ τους και επικόλλησέ τους εδώ.",
    )


def _check_names(df):
    bad = [str(c) for c in df.columns if not str(c).isascii() or to_snake(c) == ""]
    if bad:
        raise ValueError(
            f"Οι στήλες {', '.join(bad[:6])} έχουν μη λατινικούς χαρακτήρες. Τρέξε πρώτα «snake_case ονόματα» "
            "με μετατροπή σε λατινικούς — το ML pipeline δουλεύει με λατινικά ονόματα."
        )


def _disable_title_unless_titanic_names(df, config):
    """The v1 advisor extracts a title from any `name` column ('Braund, Mr. Owen' -> 'Mr').
    On ordinary names that yields an empty column and imputation fails, so keep it only when
    at least half of the names really have that shape. The name column is still dropped."""
    if not config["feature_engineering"].get("extract_title_from_name"):
        return
    column = next(c for c in df.columns if to_snake(c) == "name")
    titanic_like = df[column].dropna().astype(str).str.contains(r",\s*[^.]+\.", regex=True).mean()
    if titanic_like >= 0.5:
        return
    config["feature_engineering"]["extract_title_from_name"] = False
    config["encoding"]["one_hot"] = [c for c in config["encoding"]["one_hot"] if c != "title"]
    config["imputation"].pop("title", None)


def build_config(df, target, overrides_json=""):
    _check_names(df)
    if target:
        require_columns(df, [target])
    config = suggest_cleaning_config(profile_dataframe(df), target or None)
    _disable_title_unless_titanic_names(df, config)
    if overrides_json.strip():
        try:  # turn a JSON typo into a readable message
            overrides = json.loads(overrides_json)
        except json.JSONDecodeError as error:
            raise ValueError(f"Το JSON δεν είναι έγκυρο: {error}") from None
        if not isinstance(overrides, dict):
            raise ValueError("Το JSON πρέπει να είναι αντικείμενο { ... }.")
        config.update(overrides)
    _prune_dropped(config)
    return config


def _prune_dropped(config):
    """Rules for a column the user drops would fail later ('outliers column is missing'): remove them."""
    dropped = {to_snake(c) for c in config.get("drop_columns") or []}
    if not dropped:
        return
    for key in ("imputation", "outliers", "string_cleaning", "type_casting"):
        config[key] = {c: v for c, v in (config.get(key) or {}).items() if to_snake(c) not in dropped}
    encoding = config.setdefault("encoding", {})
    encoding["binary_map"] = {c: v for c, v in (encoding.get("binary_map") or {}).items() if to_snake(c) not in dropped}
    encoding["one_hot"] = [c for c in encoding.get("one_hot") or [] if to_snake(c) not in dropped]
    scaling = config.setdefault("scaling", {"method": "standard"})
    log_of_dropped = {f"{c}_log" for c in dropped}
    scaling["columns"] = [c for c in scaling.get("columns") or [] if to_snake(c) not in dropped | log_of_dropped]
    if config.get("target_column") and to_snake(config["target_column"]) in dropped:
        raise ValueError("Η στήλη-στόχος είναι στα drop_columns.")


@operation(
    "ml.suggest_config", "Πρόταση κανόνων ML",
    "Δείχνει τους κανόνες που θα εφαρμόσει το ML Prep (drops, γέμισμα, outliers, encoding, scaling) ως JSON για επεξεργασία",
    "ml", "inspect", SuggestParams,
)
def suggest_config(df, p, ctx):
    config = build_config(df, p.target)
    summary = [
        ("Στόχος", config.get("target_column") or "—"),
        ("Διαγραφές στηλών", len(config["drop_columns"])),
        ("Γέμισμα", len(config["imputation"])),
        ("Outliers", len(config["outliers"])),
        ("One-hot", len(config["encoding"]["one_hot"])),
        ("Scaling", len(config["scaling"]["columns"])),
    ]
    return OpOutput(sections=[cards(summary), text(json.dumps(config, ensure_ascii=False, indent=2), "Κανόνες (JSON)")])


def _split(cleaned, config):
    test_size = float(config.get("test_size") or 0)
    if test_size <= 0:
        return cleaned, None, []
    target = config.get("target_column")
    stratify = None
    notes = []
    if target and target in cleaned.columns:
        counts = cleaned[target].value_counts()
        if len(counts) <= 20 and counts.min() >= 2:
            stratify = cleaned[target]
        else:
            notes.append("Χωρίς stratify: ο στόχος έχει πολλές τιμές ή κλάσεις με μία γραμμή.")
    train, test = train_test_split(cleaned, test_size=test_size, random_state=config.get("random_state", 42), stratify=stratify)
    return train, test, notes


@operation(
    "ml.leakage_free_prep", "Train/Test χωρίς leakage",
    "Split → γέμισμα/outliers/encoding/scaling με fit μόνο στο train → train_clean.csv, test_clean.csv, preprocess.py. "
    "Τα τρέχοντα δεδομένα δεν αλλάζουν.",
    "ml", "inspect", PrepParams,
)
def leakage_free_prep(df, p, ctx):
    config = build_config(df, p.target, p.config_json)
    config["test_size"] = p.test_size
    config["random_state"] = p.random_state
    cleaned = apply_structural_cleaning(df, config)
    train, test, notes = _split(cleaned, config)
    train, test, _fitted = fit_apply_imputation_and_outliers(train, test, config)
    train, test, info = fit_apply_encoding_and_scaling(train, test, config)

    folder = Path(ctx["storage_dir"]).joinpath(*ML_FOLDER)
    for name in ML_FILES:
        (folder / name).unlink(missing_ok=True)
    export_artifacts(ctx["session_id"], train, test, config, folder=folder)
    df.to_csv(folder / "raw.csv", index=False, encoding="utf-8")  # input of preprocess.py
    (folder / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    nulls = int(train.isna().sum().sum())
    non_numeric = [c for c in train.columns if not str(train[c].dtype).startswith(("int", "float", "uint", "bool", "Int", "Float"))]
    warnings = list(notes)
    if nulls:
        warnings.append(f"Έμειναν {nulls} κενά στο train — πρόσθεσε κανόνες imputation στο JSON.")
    if non_numeric:
        warnings.append(f"Μη αριθμητικές στήλες: {', '.join(map(str, non_numeric[:10]))} — πρόσθεσέ τες σε encoding ή drop_columns.")
    files = [
        {"label": label, "name": name, "size": (folder / name).stat().st_size}
        for label, name in [("Train", "train_clean.csv"), ("Test", "test_clean.csv"), ("Script", "preprocess.py"),
                            ("Είσοδος script", "raw.csv"), ("Κανόνες", "config.json")]
        if (folder / name).exists()
    ]
    return OpOutput(
        warnings=warnings,
        message=f"Train {train.shape[0]}×{train.shape[1]}" + (f" · Test {test.shape[0]}×{test.shape[1]}" if test is not None else ""),
        sections=[
            cards([("Train", f"{train.shape[0]} × {train.shape[1]}"),
                   ("Test", f"{test.shape[0]} × {test.shape[1]}" if test is not None else "—"),
                   ("Κενά", nulls), ("Όλα αριθμητικά", "ναι" if not non_numeric else "όχι"),
                   ("Scaled", len(info["scaler"]["columns"]))]),
            downloads(files, "Αρχεία"),
            table(train.head(20), "Train (πρώτες 20 γραμμές)"),
        ],
    )
