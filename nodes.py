"""PocketFlow nodes for DataPrep Studio.

Rule for every node: prep reads shared, exec never sees shared, post writes shared.
The only DataFrame kept in memory is shared["df_cache"]["df"] (the current version).
"""

import codecs
import logging
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
from pocketflow import Node
from pydantic import ValidationError

from utils.code_gen import build_script
from utils.diff import diff_summary
from utils.file_detect import SUPPORTED_FORMATS, detect_encoding, detect_format, list_sheets, sniff_csv
from utils.file_reader import read_any
from utils.file_writer import write_any
from utils.json_safe import df_page, to_jsonable
from utils.op_registry import get_op, render_code
from utils.profile import build_profile
from utils.suggest import suggest_operations
from utils.version_store import delete_versions, load_version, save_version

logger = logging.getLogger(__name__)

PREVIEW_ROWS = 50
VALIDATION_MESSAGES = {
    "missing": "υποχρεωτικό πεδίο",
    "too_short": "χρειάζεται τουλάχιστον μία επιλογή",
    "literal_error": "μη έγκυρη επιλογή",
    "extra_forbidden": "άγνωστη παράμετρος",
}


def empty_pending():
    return {"spec_id": None, "params": None, "output": None, "error": None}


def active_steps(shared):
    return [s for s in shared["recipe"] if s["version_after"] <= shared["current_version"]]


def _friendly_error(exc):
    if isinstance(exc, (ValueError, KeyError)) and exc.args:
        return str(exc.args[0])
    return f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------- upload flow

class DetectFormatNode(Node):
    """Find format, encoding, delimiter, decimal and sheets. User overrides win."""

    def prep(self, shared):
        return shared["source"]

    def exec(self, source):
        overrides = dict(source.get("read_overrides") or {})
        if overrides.get("encoding"):
            try:  # turn a typo into a clear message instead of a LookupError later
                overrides["encoding"] = codecs.lookup(overrides["encoding"]).name
            except LookupError:
                raise ValueError(f"Άγνωστο encoding: {overrides['encoding']}") from None
        fmt = detect_format(source["path"], source["filename"])
        info = {"format": fmt, "sheets": [], "sheet": None}
        if fmt in ("csv", "json", "jsonl"):
            detected = detect_encoding(source["path"])
            info.update(
                encoding=overrides.get("encoding") or detected["encoding"],
                encoding_confidence=detected["confidence"],
                encoding_alternatives=detected["alternatives"],
            )
        if fmt == "csv":
            dialect = sniff_csv(source["path"], info["encoding"])
            info["delimiter"] = overrides.get("delimiter") or dialect["delimiter"]
            info["decimal"] = overrides.get("decimal") or dialect["decimal"]
        if fmt == "excel":
            info["sheets"] = list_sheets(source["path"])
            info["sheet"] = overrides.get("sheet") or info["sheets"][0]
        return info

    def exec_fallback(self, prep_res, exc):
        logger.exception("Format detection failed")
        return {"error": f"Δεν ήταν δυνατή η αναγνώριση του αρχείου: {_friendly_error(exc)}"}

    def post(self, shared, prep_res, info):
        if "error" in info:
            shared["pending"]["error"] = info["error"]
            return "error"
        if info["format"] not in SUPPORTED_FORMATS:
            shared["pending"]["error"] = (
                "Μη υποστηριζόμενο αρχείο. Υποστηρίζονται: CSV/TSV/TXT, Excel (.xlsx), JSON, JSONL, Parquet, Feather."
            )
            return "error"
        shared["source"].update(info)
        return "default"


class ReadFileNode(Node):
    """Read into a DataFrame. On failure, retry with the next candidate encoding."""

    def __init__(self):
        super().__init__(max_retries=4)

    def prep(self, shared):
        return shared["source"]

    def exec(self, source):
        forced = (source.get("read_overrides") or {}).get("encoding")
        candidates = [source.get("encoding")] if forced else [source.get("encoding"), *(source.get("encoding_alternatives") or [])]
        encoding = candidates[min(self.cur_retry, len(candidates) - 1)]
        if self.cur_retry:
            logger.info("Retrying read with encoding %s", encoding)
        df, notes, info = read_any(source["path"], source["format"], {
            "encoding": encoding,
            "delimiter": source.get("delimiter"),
            "decimal": source.get("decimal"),
            "sheet": source.get("sheet"),
        })
        return {"df": df, "notes": notes, "encoding": encoding, "text_columns": info["text_columns"]}

    def exec_fallback(self, prep_res, exc):
        logger.exception("Read failed")
        return {"error": f"Το αρχείο δεν διαβάστηκε: {_friendly_error(exc)}"}

    def post(self, shared, prep_res, res):
        if "error" in res:
            shared["pending"]["error"] = res["error"]
            return "error"
        if res["encoding"]:
            shared["source"]["encoding"] = res["encoding"]
        shared["source"]["read_warnings"] = res["notes"]
        shared["source"]["text_columns"] = res["text_columns"]
        shared["df_cache"] = {"version": None, "df": res["df"]}
        return "default"


# ---------------------------------------------------------------- shared by flows

class SaveVersionNode(Node):
    """Store a new version. Upload mode: v0 from df_cache. Operation mode: from pending.output."""

    def prep(self, shared):
        output = shared["pending"].get("output")
        initial = output is None
        return {
            "initial": initial,
            "storage_dir": shared["session"]["storage_dir"],
            "versions": shared["versions"],
            "current": shared["current_version"],
            "df": shared["df_cache"]["df"] if initial else output["output"].df,
            "spec_id": shared["pending"].get("spec_id"),
            "params": shared["pending"].get("params"),
            "output": output,
        }

    def exec(self, p):
        if p["initial"]:
            number, stale = 0, [v["path"] for v in p["versions"]]
        else:
            number = p["current"] + 1
            stale = [v["path"] for v in p["versions"] if v["version"] > p["current"]]
        delete_versions(stale)
        path = save_version(p["storage_dir"], number, p["df"])
        return {"version": number, "path": path}

    def post(self, shared, p, res):
        number = res["version"]
        if p["initial"]:
            shared["versions"], shared["recipe"] = [], []
        else:
            shared["versions"] = [v for v in shared["versions"] if v["version"] <= p["current"]]
            shared["recipe"] = [s for s in shared["recipe"] if s["version_after"] <= p["current"]]
        step = None
        if not p["initial"]:
            spec = get_op(p["spec_id"])
            step = len(shared["recipe"]) + 1
            shared["recipe"].append({
                "step": step,
                "op": spec.id,
                "label": spec.label,
                "params": p["params"].model_dump(mode="json"),
                "code": p["output"]["code"],
                "summary": p["output"]["output"].message,
                "version_before": p["current"],
                "version_after": number,
                "at": datetime.now().isoformat(timespec="seconds"),
            })
        shared["versions"].append({
            "version": number, "path": res["path"], "shape": [int(x) for x in p["df"].shape], "step": step,
        })
        shared["current_version"] = number
        shared["df_cache"] = {"version": number, "df": p["df"]}
        return "default"


class ProfileNode(Node):
    def prep(self, shared):
        return shared["df_cache"]

    def exec(self, cache):
        return build_profile(cache["df"])

    def post(self, shared, cache, profile):
        profile["version"] = cache["version"]
        shared["profile"] = profile
        return "default"


class SuggestNode(Node):
    """Heuristic suggestions (no LLM in the MVP)."""

    def prep(self, shared):
        return shared["profile"]

    def exec(self, profile):
        return suggest_operations(profile)

    def post(self, shared, prep_res, suggestions):
        shared["suggestions"] = suggestions
        return "default"


class LoadCurrentDataNode(Node):
    def prep(self, shared):
        current = shared["current_version"]
        path = next(v["path"] for v in shared["versions"] if v["version"] == current)
        return shared["df_cache"], current, path

    def exec(self, inputs):
        cache, current, path = inputs
        if cache.get("version") == current and cache.get("df") is not None:
            return cache
        logger.info("Loading version %s from disk", current)
        return {"version": current, "df": load_version(path)}

    def post(self, shared, prep_res, cache):
        shared["df_cache"] = cache
        return "default"


class BuildErrorNode(Node):
    def prep(self, shared):
        return shared["pending"].get("error") or "Άγνωστο σφάλμα", (shared.get("request") or {}).get("op")

    def post(self, shared, prep_res, exec_res):
        message, op = prep_res
        shared["result"] = {"status": "error", "op": op, "message": message, "sections": [], "warnings": []}
        shared["pending"] = empty_pending()
        return "default"


# ---------------------------------------------------------------- operation flow

class ResolveOperationNode(Node):
    """Find the button in the registry and validate its params."""

    def prep(self, shared):
        return shared["request"]

    def exec(self, request):
        spec = get_op(request.get("op") or "")
        params = spec.params_model.model_validate(request.get("params") or {})
        return {"spec_id": spec.id, "kind": spec.kind, "params": params}

    def exec_fallback(self, request, exc):
        if isinstance(exc, ValidationError):
            schema = get_op(request["op"]).params_model.model_json_schema()["properties"]
            parts = []
            for error in exc.errors():
                field = str(error["loc"][0]) if error["loc"] else ""
                title = schema.get(field, {}).get("title", field)
                parts.append(f"{title}: {VALIDATION_MESSAGES.get(error['type'], error['msg'])}")
            return {"error": "Λάθος παράμετροι — " + "; ".join(parts)}
        return {"error": _friendly_error(exc)}

    def post(self, shared, request, res):
        if "error" in res:
            shared["pending"]["error"] = res["error"]
            return "invalid"
        shared["pending"].update(spec_id=res["spec_id"], params=res["params"])
        return res["kind"]


class ExecuteOperationNode(Node):
    """Run the operation function. Transform ops also get a diff and their pandas snippet."""

    def prep(self, shared):
        return {
            "df": shared["df_cache"]["df"],
            "spec_id": shared["pending"]["spec_id"],
            "params": shared["pending"]["params"],
            "preview": bool(shared["request"].get("preview")),
            "ctx": {
                "source": shared["source"],
                "session_id": shared["session"]["id"],
                "storage_dir": shared["session"]["storage_dir"],
                "attachments": shared.get("attachments", {}),
            },
        }

    def exec(self, p):
        spec = get_op(p["spec_id"])
        logger.info("Running %s %s", spec.id, p["params"].model_dump())
        output = spec.fn(p["df"], p["params"], p["ctx"])
        if spec.kind == "transform":
            assert output.df is not None, f"{spec.id} must return a DataFrame"
            code = render_code(spec, p["params"], p["ctx"])
            return {"output": output, "diff": diff_summary(p["df"], output.df), "code": code}
        assert output.df is None, f"{spec.id} is inspect-only and must not return a DataFrame"
        return {"output": output, "diff": None, "code": None}

    def exec_fallback(self, p, exc):
        if isinstance(exc, ValueError):  # expected: bad column, wrong value for the user's data
            logger.warning("Operation %s rejected: %s", p["spec_id"], exc)
        else:
            logger.exception("Operation %s failed", p["spec_id"])
        return {"error": _friendly_error(exc)}

    def post(self, shared, p, res):
        if "error" in res:
            shared["pending"]["error"] = res["error"]
            return "error"
        shared["pending"]["output"] = res
        if res["diff"] is None:
            return "inspect_done"
        return "preview_done" if p["preview"] else "transform_done"


class BuildResultNode(Node):
    """Turn the operation output into JSON for React."""

    def prep(self, shared):
        return shared["pending"], bool(shared["request"].get("preview"))

    def exec(self, inputs):
        pending, preview = inputs
        spec = get_op(pending["spec_id"])
        res = pending["output"]
        output = res["output"]
        result = {
            "status": "ok",
            "op": spec.id,
            "label": spec.label,
            "kind": spec.kind,
            "preview": preview,
            "message": output.message,
            "warnings": output.warnings,
            "sections": to_jsonable(output.sections),
            "code": res["code"],
            "diff": res["diff"],
            "params": pending["params"].model_dump(mode="json"),
        }
        if preview:
            result["preview_rows"] = df_page(output.df, 1, PREVIEW_ROWS)
        return result

    def post(self, shared, prep_res, result):
        shared["result"] = result
        shared["pending"] = empty_pending()
        return "default"


# ---------------------------------------------------------------- undo / redo / checkout

class MoveVersionNode(Node):
    def prep(self, shared):
        return shared["request"].get("target"), shared["current_version"], [v["version"] for v in shared["versions"]]

    def exec(self, inputs):
        target, current, versions = inputs
        if target == "undo":
            new = current - 1
        elif target == "redo":
            new = current + 1
        else:
            new = int(target)
        if new not in versions:
            raise ValueError({"undo": "Δεν υπάρχει άλλο βήμα για αναίρεση.", "redo": "Δεν υπάρχει βήμα για επανάληψη."}
                             .get(target, f"Η έκδοση {target} δεν υπάρχει."))
        return new

    def exec_fallback(self, prep_res, exc):
        return {"error": _friendly_error(exc)}

    def post(self, shared, prep_res, new):
        if isinstance(new, dict):
            shared["pending"]["error"] = new["error"]
            return "error"
        shared["current_version"] = new
        shared["result"] = {"status": "ok", "message": f"Τρέχουσα έκδοση: v{new}", "sections": [], "warnings": []}
        return "default"


# ---------------------------------------------------------------- export

class WriteExportNode(Node):
    def prep(self, shared):
        request = shared["request"]
        stem = shared["source"]["filename"].rsplit(".", 1)[0] + f"_v{shared['current_version']}"
        return shared["df_cache"]["df"], request, shared["session"]["storage_dir"], stem

    def exec(self, inputs):
        df, request, storage_dir, stem = inputs
        return write_any(
            df, request.get("format", "csv"), f"{storage_dir}/exports", stem,
            encoding=request.get("encoding") or "utf-8-sig", delimiter=request.get("delimiter") or ",",
        )

    def exec_fallback(self, prep_res, exc):
        return {"error": _friendly_error(exc)}

    def post(self, shared, prep_res, res):
        # Last node of its flow, so it writes the error result itself (no extra branch).
        if "error" in res:
            shared["result"] = {"status": "error", "message": res["error"], "sections": [], "warnings": []}
        else:
            shared["result"] = {"status": "ok", "payload": res}
        return None


class AttachFileNode(Node):
    """Read a second file (for joins) with the same detection as the main upload. Retries next encoding."""

    def __init__(self):
        super().__init__(max_retries=4)

    def prep(self, shared):
        return shared["request"], shared["session"]["storage_dir"]

    def exec(self, inputs):
        request, storage_dir = inputs
        path, filename = request["path"], request["filename"]
        fmt = detect_format(path, filename)
        if fmt not in SUPPORTED_FORMATS:
            raise ValueError(f"Μη υποστηριζόμενο αρχείο: {filename}")
        meta = {"name": filename, "filename": filename, "format": fmt, "path": path}
        candidates = [None]
        if fmt in ("csv", "json", "jsonl"):
            detected = detect_encoding(path)
            candidates = [detected["encoding"], *detected["alternatives"]]
        encoding = candidates[min(self.cur_retry, len(candidates) - 1)]
        if fmt == "csv":
            meta.update(sniff_csv(path, encoding))
        if fmt == "excel":
            meta["sheet"] = list_sheets(path)[0]
        meta["encoding"] = encoding
        df, _notes, info = read_any(path, fmt, meta)
        meta["text_columns"] = info["text_columns"]
        data_path = Path(storage_dir) / "attachments" / f"{uuid.uuid4().hex}.pkl"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_pickle(data_path)
        meta["data_path"] = str(data_path)
        meta.update(shape=[int(x) for x in df.shape], columns=[str(c) for c in df.columns])
        return meta

    def exec_fallback(self, prep_res, exc):
        return {"error": f"Το δεύτερο αρχείο δεν διαβάστηκε: {_friendly_error(exc)}"}

    def post(self, shared, prep_res, meta):
        if "error" in meta:
            shared["result"] = {"status": "error", "message": meta["error"], "sections": [], "warnings": []}
            return None
        shared.setdefault("attachments", {})[meta["name"]] = meta
        shared["result"] = {"status": "ok", "message": f"{meta['filename']}: {meta['shape'][0]} × {meta['shape'][1]}",
                            "sections": [], "warnings": []}
        return None


# ---------------------------------------------------------------- recipe replay

class ValidateRecipeNode(Node):
    """Every step must be a known transform with valid params, before anything changes."""

    def prep(self, shared):
        return shared["request"].get("steps") or []

    def exec(self, steps):
        if not steps:
            raise ValueError("Το recipe δεν έχει βήματα.")
        problems = []
        for number, step in enumerate(steps, start=1):
            try:  # collect every problem instead of stopping at the first
                spec = get_op(step.get("op", ""))
                if spec.kind != "transform":
                    problems.append(f"Βήμα {number}: το '{spec.label}' δεν αλλάζει δεδομένα")
                spec.params_model.model_validate(step.get("params") or {})
            except (KeyError, ValidationError) as error:
                problems.append(f"Βήμα {number} ({step.get('op')}): {_friendly_error(error)}")
        return {"steps": steps, "problems": problems}

    def exec_fallback(self, prep_res, exc):
        return {"steps": [], "problems": [_friendly_error(exc)]}

    def post(self, shared, prep_res, res):
        if res["problems"]:
            shared["pending"]["error"] = "Μη έγκυρο recipe — " + "; ".join(res["problems"][:5])
            return "error"
        shared["replay"] = {"steps": res["steps"], "start_version": shared["current_version"], "done": [], "failed": None}
        return "default"


class ReplayStepNode(Node):
    """Turn recipe step `step_index` (BatchFlow param) into an operation request; skip after a failure."""

    def prep(self, shared):
        return shared["replay"], self.params["step_index"]

    def post(self, shared, prep_res, exec_res):
        replay, index = prep_res
        if replay["failed"] is not None:
            return "skip"
        step = replay["steps"][index]
        shared["request"] = {"op": step["op"], "params": step.get("params") or {}, "preview": False}
        shared["result"] = None
        return "default"


class RecordStepNode(Node):
    def prep(self, shared):
        return shared["replay"], self.params["step_index"], shared["result"] or {}

    def post(self, shared, prep_res, exec_res):
        replay, index, result = prep_res
        step = replay["steps"][index]
        ok = result.get("status") == "ok"
        replay["done"].append({
            "βήμα": index + 1,
            "λειτουργία": step.get("label") or step["op"],
            "αποτέλεσμα": "✓" if ok else "✗",
            "μήνυμα": result.get("message", ""),
        })
        if not ok:
            replay["failed"] = index
        return "default"


class ReplayReportNode(Node):
    """On failure, move back to the version before the replay (the finished steps stay available as redo)."""

    def prep(self, shared):
        return shared["replay"]

    def post(self, shared, replay, exec_res):
        total = len(replay["steps"])
        if replay["failed"] is None:
            message = f"Εφαρμόστηκαν και τα {total} βήματα"
            warnings = []
        else:
            shared["current_version"] = replay["start_version"]
            message = f"Σταμάτησε στο βήμα {replay['failed'] + 1} από {total}"
            warnings = [f"Τα δεδομένα επέστρεψαν στη v{replay['start_version']}. "
                        "Διόρθωσε το αρχείο ή το βήμα· όσα βήματα πέτυχαν είναι διαθέσιμα με Επανάληψη (↷)."]
        shared["result"] = {
            "status": "ok", "label": "Εφαρμογή recipe", "kind": "transform", "message": message,
            "warnings": warnings,
            "sections": to_jsonable([{"type": "table", "title": "Βήματα", "data": pd.DataFrame(replay["done"])}]),
            "replay_failed": replay["failed"] is not None,
        }
        shared.pop("replay", None)
        shared["pending"] = empty_pending()
        return "default"


class GenerateScriptNode(Node):
    def prep(self, shared):
        return shared["source"], active_steps(shared)

    def exec(self, inputs):
        source, steps = inputs
        return build_script(source, steps)

    def post(self, shared, prep_res, script):
        shared["result"] = {"status": "ok", "payload": {"script": script}}
        return "default"
