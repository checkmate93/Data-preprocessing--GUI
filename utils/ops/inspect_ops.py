"""Read-only buttons: they return sections and never a DataFrame."""

import io
from typing import Literal

import pandas as pd
from pydantic import Field

from utils.op_registry import (
    OpOutput,
    Params,
    bar,
    box,
    cards,
    heatmap,
    histogram,
    line,
    operation,
    require_columns,
    table,
    text,
)
from utils.ops.fields import Aggregation, aggregations_field, choice, column_field, columns_field
from utils.ops.helpers import column_kind


@operation("inspect.info", "Info", "df.info(): τύποι, μη κενές τιμές, μνήμη", "inspect", "inspect")
def info(df, p, ctx):
    buffer = io.StringIO()
    df.info(buf=buffer, memory_usage="deep")
    n = len(df)
    rows = [
        {
            "στήλη": c,
            "dtype": str(df[c].dtype),
            "μη κενές": int(df[c].notna().sum()),
            "κενές": int(df[c].isna().sum()),
            "κενές %": round(df[c].isna().mean() * 100, 2) if n else 0.0,
            "μοναδικές": int(df[c].nunique(dropna=True)),
        }
        for c in df.columns
    ]
    memory = round(df.memory_usage(deep=True).sum() / 1024 ** 2, 2)
    return OpOutput(sections=[
        cards([("Γραμμές", n), ("Στήλες", df.shape[1]), ("Μνήμη", f"{memory} MB")]),
        table(rows, "Ανά στήλη"),
        text(buffer.getvalue(), "df.info()"),
    ])


class DescribeParams(Params):
    include: Literal["numeric", "categorical", "datetime", "all"] = choice(
        "numeric", "Τύπος στηλών",
        {"numeric": "Αριθμητικές", "categorical": "Κείμενο / κατηγορίες", "datetime": "Ημερομηνίες", "all": "Όλες"},
    )
    extra_stats: bool = Field(True, title="Skew & kurtosis (για αριθμητικές)")


@operation("inspect.describe", "Describe", "df.describe(): στατιστικά ανά στήλη", "inspect", "inspect", DescribeParams)
def describe(df, p, ctx):
    kinds = {c: column_kind(df[c]) for c in df.columns}
    wanted = {
        "numeric": {"numeric"}, "categorical": {"text", "boolean"},
        "datetime": {"datetime"}, "all": {"numeric", "text", "boolean", "datetime"},
    }[p.include]
    selected = [c for c in df.columns if kinds[c] in wanted]
    if not selected:
        return OpOutput(sections=[text("Δεν υπάρχουν στήλες αυτού του τύπου.")])
    frame = df[selected].describe(include="all").T
    if p.extra_stats:
        numeric = [c for c in selected if kinds[c] == "numeric"]
        if numeric:
            frame["skew"] = df[numeric].skew()
            frame["kurtosis"] = df[numeric].kurt()
    frame = frame.dropna(axis=1, how="all")
    frame.index.name = "στήλη"
    return OpOutput(sections=[table(frame.reset_index(), f"describe() — {len(selected)} στήλες")])


class HeadParams(Params):
    mode: Literal["head", "tail", "sample"] = choice(
        "head", "Ποιες γραμμές", {"head": "Πρώτες (head)", "tail": "Τελευταίες (tail)", "sample": "Τυχαίο δείγμα"})
    n: int = Field(10, ge=1, le=500, title="Πλήθος γραμμών")
    seed: int = Field(42, title="Random seed (για δείγμα)")


@operation("inspect.head_tail_sample", "Head / Tail / Sample", "Δες συγκεκριμένες γραμμές", "inspect", "inspect", HeadParams)
def head_tail_sample(df, p, ctx):
    if p.mode == "head":
        frame = df.head(p.n)
    elif p.mode == "tail":
        frame = df.tail(p.n)
    else:
        frame = df.sample(min(p.n, len(df)), random_state=p.seed)
    return OpOutput(sections=[table(frame.reset_index(names="γραμμή"), f"{p.mode}({p.n})")])


@operation("inspect.missing", "Ανάλυση κενών", "Πόσες κενές τιμές έχει κάθε στήλη", "inspect", "inspect")
def missing(df, p, ctx):
    counts = df.isna().sum()
    n = len(df)
    rows = [
        {"στήλη": c, "dtype": str(df[c].dtype), "κενές": int(counts[c]), "κενές %": round(counts[c] / n * 100, 2) if n else 0}
        for c in df.columns
    ]
    rows.sort(key=lambda r: r["κενές"], reverse=True)
    with_missing = [r for r in rows if r["κενές"]]
    sections = [cards([
        ("Κενά κελιά", int(counts.sum())),
        ("Γραμμές με ≥1 κενό", int(df.isna().any(axis=1).sum())),
        ("Πλήρεις γραμμές", int((~df.isna().any(axis=1)).sum())),
        ("Στήλες με κενά", len(with_missing)),
    ])]
    if with_missing:
        sections.append(bar([r["στήλη"] for r in with_missing], [r["κενές %"] for r in with_missing], "Κενές τιμές %", "%"))
    sections.append(table(rows, "Ανά στήλη"))
    return OpOutput(sections=sections)


class ValueCountsParams(Params):
    column: str = column_field()
    top: int = Field(20, ge=1, le=500, title="Πόσες τιμές")
    dropna: bool = Field(False, title="Αγνόησε τις κενές")


@operation("inspect.value_counts", "Συχνότητες τιμών", "value_counts() για μία στήλη", "inspect", "inspect", ValueCountsParams)
def value_counts(df, p, ctx):
    require_columns(df, [p.column])
    counts = df[p.column].value_counts(dropna=p.dropna)
    total = int(counts.sum())
    shown = counts.head(p.top)
    labels = ["(κενό)" if str(v) in ("nan", "<NA>", "NaT", "None") else str(v) for v in shown.index]
    rows = [
        {"τιμή": label, "πλήθος": int(count), "%": round(count / total * 100, 2) if total else 0}
        for label, count in zip(labels, shown.values)
    ]
    return OpOutput(sections=[
        cards([("Διαφορετικές τιμές", int(df[p.column].nunique(dropna=True))), ("Εμφανίζονται", len(rows))]),
        bar(labels, [int(v) for v in shown.values], f"Top {len(rows)} — {p.column}"),
        table(rows),
    ])


class DuplicatesParams(Params):
    columns: list[str] = columns_field("Έλεγχος μόνο σε αυτές τις στήλες", "Κενό = ολόκληρη η γραμμή")
    show: int = Field(20, ge=1, le=500, title="Παραδείγματα")


@operation("inspect.duplicates", "Διπλότυπα", "Ποιες γραμμές επαναλαμβάνονται", "inspect", "inspect", DuplicatesParams)
def duplicates(df, p, ctx):
    subset = require_columns(df, p.columns) or None
    extra = df.duplicated(subset=subset, keep="first")
    involved = df.duplicated(subset=subset, keep=False)
    sections = [cards([("Διπλότυπες (πέραν της 1ης)", int(extra.sum())), ("Γραμμές που εμπλέκονται", int(involved.sum()))])]
    if involved.any():
        sample = df[involved].sort_values(subset or list(df.columns), kind="stable", na_position="last").head(p.show)
        sections.append(table(sample.reset_index(names="γραμμή"), "Παραδείγματα"))
    return OpOutput(sections=sections)


@operation("inspect.file_encoding", "Encoding αρχείου", "Encoding, διαχωριστικό και format που εντοπίστηκαν", "inspect", "inspect")
def file_encoding(df, p, ctx):
    source = ctx["source"]
    items = [("Format", source.get("format")), ("Αρχείο", source.get("filename"))]
    if source.get("format") == "csv":
        items += [
            ("Encoding", source.get("encoding")),
            ("Βεβαιότητα", source.get("encoding_confidence")),
            ("Διαχωριστικό", {"\t": "TAB"}.get(source.get("delimiter"), source.get("delimiter"))),
            ("Δεκαδικό", source.get("decimal")),
        ]
    if source.get("sheets"):
        items.append(("Sheet", source.get("sheet")))
    note = (
        "Αν βλέπεις περίεργους χαρακτήρες (π.χ. 'Ξ‘Ξ' αντί για 'Α'), πάτα «Ξαναδιάβασε το αρχείο» "
        f"και δοκίμασε: {', '.join(source.get('encoding_alternatives') or [])}."
    )
    sections = [cards(items), text(note)]
    if source.get("read_warnings"):
        sections.append(text("\n".join(source["read_warnings"]), "Προειδοποιήσεις ανάγνωσης"))
    return OpOutput(sections=sections)


# ---------------------------------------------------------------- phase 2

@operation("inspect.unique", "Μοναδικές τιμές", "nunique ανά στήλη, cardinality, σταθερές στήλες και πιθανά IDs", "inspect", "inspect")
def unique(df, p, ctx):
    n = len(df)
    rows = []
    for c in df.columns:
        u = int(df[c].nunique(dropna=True))
        note = "σταθερή" if u <= 1 else "πιθανό ID" if n > 1 and u == n else "χαμηλό cardinality" if u <= 10 else ""
        rows.append({"στήλη": c, "μοναδικές": u, "ratio %": round(u / n * 100, 2) if n else 0, "σχόλιο": note})
    rows.sort(key=lambda r: r["μοναδικές"])
    return OpOutput(sections=[table(rows, "Cardinality")])


@operation("inspect.dtypes_check", "Έλεγχος τύπων", "Βρίσκει αριθμούς/ημερομηνίες σε κείμενο, μικτούς τύπους και placeholders", "inspect", "inspect")
def dtypes_check(df, p, ctx):
    from utils.profile import build_profile  # lazy: utils.profile imports this package

    labels = {
        "looks_numeric": "αριθμοί ως κείμενο → «Αυτόματοι τύποι» ή «→ Αριθμός»",
        "looks_date": "ημερομηνίες ως κείμενο → «→ Ημερομηνία»",
        "placeholders": "τιμές τύπου N/A, -, ? → «Ενοποίηση κενών»",
        "whitespace": "κενά στην αρχή/τέλος → «Καθάρισμα κενών»",
        "case_variants": "ίδιες τιμές με άλλη γραφή → «Ενοποίηση ετικετών»",
        "id_like": "μοναδική τιμή ανά γραμμή (ID)",
        "constant": "σταθερή τιμή → «Διαγραφή με κανόνα»",
        "high_missing": "≥60% κενά",
    }
    rows = []
    for column, meta in build_profile(df)["columns"].items():
        mixed = column_kind(df[column]) == "text" and df[column].dropna().map(type).nunique() > 1
        for flag in meta["flags"] + (["mixed"] if mixed else []):
            rows.append({"στήλη": column, "dtype": meta["dtype"], "εύρημα": labels.get(flag, "μικτοί python τύποι")})
    if not rows:
        return OpOutput(sections=[text("Δεν βρέθηκαν προβλήματα τύπων. 👍")])
    return OpOutput(sections=[table(rows, f"{len(rows)} ευρήματα")])


class CorrelationParams(Params):
    method: Literal["pearson", "spearman", "kendall"] = choice(
        "pearson", "Μέθοδος", {"pearson": "Pearson (γραμμική)", "spearman": "Spearman (κατάταξη)", "kendall": "Kendall"})
    top: int = Field(15, ge=1, le=100, title="Πόσα ισχυρότερα ζεύγη")


@operation("inspect.correlation", "Συσχετίσεις", "df.corr() με heatmap και τα ισχυρότερα ζεύγη", "inspect", "inspect", CorrelationParams)
def correlation(df, p, ctx):
    numeric = [c for c in df.columns if column_kind(df[c]) in ("numeric", "boolean")]
    if len(numeric) < 2:
        return OpOutput(sections=[text("Χρειάζονται τουλάχιστον 2 αριθμητικές στήλες.")])
    corr = df[numeric].astype("float64").corr(method=p.method)
    pairs = [
        {"στήλη Α": a, "στήλη Β": b, "r": round(float(corr.loc[a, b]), 4)}
        for i, a in enumerate(numeric) for b in numeric[i + 1:] if pd.notna(corr.loc[a, b])
    ]
    pairs.sort(key=lambda r: abs(r["r"]), reverse=True)
    return OpOutput(sections=[heatmap(corr, f"Συσχέτιση ({p.method})", diverging=True), table(pairs[: p.top], "Ισχυρότερα ζεύγη")])


class OutlierReportParams(Params):
    columns: list[str] = columns_field(description="Κενό = όλες οι αριθμητικές στήλες")
    z: float = Field(3.0, gt=0, le=10, title="Όριο z-score")


@operation("inspect.outliers", "Ανάλυση outliers", "IQR και z-score ανά αριθμητική στήλη, με boxplot", "inspect", "inspect", OutlierReportParams)
def outliers(df, p, ctx):
    columns = require_columns(df, p.columns) or [c for c in df.columns if column_kind(df[c]) == "numeric"]
    if not columns:
        return OpOutput(sections=[text("Δεν υπάρχουν αριθμητικές στήλες.")])
    rows = []
    for c in columns:
        s = df[c].astype("float64").dropna()
        if s.empty:
            continue
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr_count = int(((s < q1 - 1.5 * (q3 - q1)) | (s > q3 + 1.5 * (q3 - q1))).sum())
        std = s.std()
        z_count = int((((s - s.mean()) / std).abs() > p.z).sum()) if std else 0
        rows.append({"στήλη": c, "IQR outliers": iqr_count, f"|z|>{p.z}": z_count, "min": s.min(), "max": s.max()})
    return OpOutput(sections=[box(df, columns, "Boxplot"), table(rows, "Ανά στήλη")])


@operation("inspect.memory", "Μνήμη", "memory_usage(deep=True) και πόσο μπορεί να μειωθεί", "inspect", "inspect")
def memory(df, p, ctx):
    from utils.ops.helpers import downcast_numeric

    usage = df.memory_usage(deep=True, index=False)
    _, savings = downcast_numeric(df)
    saved = {r["column"]: r for r in savings}
    rows = [
        {"στήλη": c, "dtype": str(df[c].dtype), "KB": round(usage[c] / 1024, 1),
         "πρόταση": f"→ {saved[c]['to']} (−{saved[c]['saved_kb']} KB)" if c in saved else ""}
        for c in df.columns
    ]
    rows.sort(key=lambda r: r["KB"], reverse=True)
    total_saved = sum(r["saved_kb"] for r in savings)
    return OpOutput(sections=[
        cards([("Σύνολο", f"{usage.sum() / 1024 ** 2:.2f} MB"), ("Πιθανή εξοικονόμηση", f"{total_saved / 1024:.2f} MB")]),
        table(rows, "Ανά στήλη"),
    ])


@operation("inspect.quality_score", "Data Quality Score", "Πληρότητα, μοναδικότητα, εγκυρότητα, συνέπεια (0–100)", "inspect", "inspect")
def quality_score(df, p, ctx):
    from utils.profile import build_profile

    profile = build_profile(df)
    q = profile["quality"]
    explain = [
        {"διάσταση": "Πληρότητα", "σκορ": q["completeness"], "τι μετράει": "% κελιών που δεν είναι κενά"},
        {"διάσταση": "Μοναδικότητα", "σκορ": q["uniqueness"], "τι μετράει": "% γραμμών που δεν είναι διπλότυπες"},
        {"διάσταση": "Εγκυρότητα", "σκορ": q["validity"], "τι μετράει": "% στηλών χωρίς αριθμούς/ημερομηνίες ως κείμενο ή placeholders"},
        {"διάσταση": "Συνέπεια", "σκορ": q["consistency"], "τι μετράει": "% στηλών χωρίς περιττά κενά ή παραλλαγές γραφής"},
    ]
    return OpOutput(sections=[cards([("Συνολικό σκορ", f"{q['total']}/100")]), table(explain)])


class ColumnProfileParams(Params):
    column: str = column_field()
    bins: int = Field(20, ge=2, le=100, title="Κάδοι histogram")


@operation("inspect.column_profile", "Προφίλ στήλης", "Όλα τα στατιστικά και η κατανομή μίας στήλης", "inspect", "inspect", ColumnProfileParams)
def column_profile(df, p, ctx):
    require_columns(df, [p.column])
    s = df[p.column]
    kind = column_kind(s)
    items = [("Τύπος", str(s.dtype)), ("Κενές", f"{int(s.isna().sum())} ({s.isna().mean() * 100:.1f}%)"),
             ("Μοναδικές", int(s.nunique()))]
    sections = []
    if kind == "numeric":
        v = s.dropna()
        items += [("Min", v.min()), ("Median", v.median()), ("Mean", round(v.mean(), 4)), ("Max", v.max()),
                  ("Std", round(v.std(), 4)), ("Skew", round(v.skew(), 3) if len(v) > 2 else None)]
        sections = [histogram(s, p.bins, "Κατανομή"), box(df, [p.column])]
    elif kind == "datetime":
        v = s.dropna()
        items += [("Από", v.min()), ("Έως", v.max())]
        per_month = v.dt.to_period("M").value_counts().sort_index()
        sections = [line([str(i) for i in per_month.index], {"γραμμές": per_month.tolist()}, "Γραμμές ανά μήνα")]
    else:
        counts = s.value_counts().head(20)
        lengths = s.dropna().astype(str).str.len()
        items += [("Συχνότερη", counts.index[0] if len(counts) else None), ("Μήκος (min–max)", f"{lengths.min()}–{lengths.max()}" if len(lengths) else "")]
        sections = [bar([str(i) for i in counts.index], counts.tolist(), "Top 20 τιμές")]
    return OpOutput(sections=[cards(items, p.column), *sections])


class GroupByParams(Params):
    by: list[str] = columns_field("Ομαδοποίηση κατά", required=True)
    aggregations: list[Aggregation] = aggregations_field()


def agg_spec(aggregations):
    return {f"{a.column}_{a.func}": (a.column, a.func) for a in aggregations}


def run_groupby(df, by, aggregations):
    return df.groupby(by, dropna=False).agg(**agg_spec(aggregations)).reset_index()


@operation("inspect.groupby", "Group-by σύνοψη", "groupby().agg() — μόνο προβολή, δεν αλλάζει τα δεδομένα", "inspect", "inspect", GroupByParams)
def groupby_preview(df, p, ctx):
    require_columns(df, p.by + [a.column for a in p.aggregations], at_least=1)
    result = run_groupby(df, p.by, p.aggregations)
    return OpOutput(sections=[cards([("Ομάδες", len(result))]), table(result, "Αποτέλεσμα")])


class CrosstabParams(Params):
    rows: str = column_field("Γραμμές")
    cols: str = column_field("Στήλες")
    normalize: Literal["none", "all", "index", "columns"] = choice(
        "none", "Ποσοστά", {"none": "Πλήθη", "all": "% του συνόλου", "index": "% ανά γραμμή", "columns": "% ανά στήλη"})


@operation("inspect.crosstab", "Crosstab", "pd.crosstab() δύο στηλών, με heatmap", "inspect", "inspect", CrosstabParams)
def crosstab(df, p, ctx):
    require_columns(df, [p.rows, p.cols])
    normalize = False if p.normalize == "none" else p.normalize
    result = pd.crosstab(df[p.rows], df[p.cols], normalize=normalize)
    if normalize:
        result = (result * 100).round(2)
    result = result.iloc[:40, :40]
    return OpOutput(sections=[heatmap(result, "Heatmap"), table(result.reset_index(), "Πίνακας")])
