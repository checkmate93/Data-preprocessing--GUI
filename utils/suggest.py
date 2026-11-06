"""Heuristic suggestions: which buttons make sense for this dataset (no LLM, no network)."""


def suggest_operations(profile):
    """Input: build_profile output. Output: [{"op", "params", "reason"}] in a useful order."""
    columns = profile["columns"]
    by_flag = lambda flag: [name for name, meta in columns.items() if flag in meta["flags"]]  # noqa: E731
    suggestions = []

    if profile["names_not_snake"]:
        suggestions.append({
            "op": "columns.snake_case", "params": {},
            "reason": f"{len(profile['names_not_snake'])} ονόματα στηλών δεν είναι snake_case",
        })
    placeholders = by_flag("placeholders")
    if placeholders:
        suggestions.append({
            "op": "missing.standardize", "params": {"columns": placeholders},
            "reason": f"Κείμενα όπως 'N/A', '-', '?' στις στήλες: {', '.join(placeholders)}",
        })
    whitespace = by_flag("whitespace")
    if whitespace:
        suggestions.append({
            "op": "text.strip", "params": {"columns": whitespace},
            "reason": f"Κενά στην αρχή/τέλος ή διπλά κενά: {', '.join(whitespace)}",
        })
    variants = [c for c in by_flag("case_variants") if columns[c].get("kind") == "categorical"]
    if variants:
        suggestions.append({
            "op": "categorical.standardize_labels", "params": {"columns": variants},
            "reason": "Ίδιες τιμές με διαφορετική γραφή (κεφαλαία/τόνοι/κενά): " + ", ".join(variants),
        })
    numeric_text = by_flag("looks_numeric")
    date_text = by_flag("looks_date")
    if numeric_text or date_text:
        suggestions.append({
            "op": "types.auto_infer", "params": {"columns": numeric_text + date_text},
            "reason": "Αριθμοί ή ημερομηνίες αποθηκευμένα ως κείμενο: " + ", ".join(numeric_text + date_text),
        })
    constant = by_flag("constant")
    high_missing = by_flag("high_missing")
    if constant or high_missing:
        drop = list(dict.fromkeys(constant + high_missing))
        suggestions.append({
            "op": "columns.drop", "params": {"columns": drop},
            "reason": "Στήλες σταθερές ή με ≥60% κενά: " + ", ".join(drop),
        })
    if profile["duplicates_count"]:
        suggestions.append({
            "op": "duplicates.drop", "params": {},
            "reason": f"{profile['duplicates_count']} διπλότυπες γραμμές",
        })
    with_missing = [n for n, m in columns.items() if m["null_count"] and "high_missing" not in m["flags"]]
    if with_missing:
        suggestions.append({
            "op": "missing.smart_fill", "params": {"columns": with_missing},
            "reason": f"Κενές τιμές σε {len(with_missing)} στήλες",
        })
    return suggestions


if __name__ == "__main__":
    demo = {
        "names_not_snake": ["A B"], "duplicates_count": 2,
        "columns": {"a": {"flags": ["whitespace"], "null_count": 1}},
    }
    ops = [s["op"] for s in suggest_operations(demo)]
    assert ops == ["columns.snake_case", "text.strip", "duplicates.drop", "missing.smart_fill"], ops
    print("suggest ok")
