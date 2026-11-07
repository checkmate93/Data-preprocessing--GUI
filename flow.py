"""Flows for DataPrep Studio. See docs/design.md for the diagrams."""

from pocketflow import BatchFlow, Flow, Node

from nodes import (
    AttachFileNode,
    BuildErrorNode,
    ChatAnswerNode,
    ChatStartNode,
    DecideActionNode,
    ToolRequestNode,
    ToolResultNode,
    empty_chat,
    BuildResultNode,
    DetectFormatNode,
    ExecuteOperationNode,
    GenerateScriptNode,
    LoadCurrentDataNode,
    MoveVersionNode,
    ProfileNode,
    ReadFileNode,
    RecordStepNode,
    ReplayReportNode,
    ReplayStepNode,
    ResolveOperationNode,
    SaveVersionNode,
    SuggestNode,
    ValidateRecipeNode,
    WriteExportNode,
    empty_pending,
)


def create_shared(session_id, storage_dir, source_path, filename, size_bytes, advisor_mode="heuristic"):
    return {
        "session": {"id": session_id, "storage_dir": storage_dir, "advisor_mode": advisor_mode},
        "source": {"filename": filename, "path": source_path, "size_bytes": size_bytes, "read_overrides": {}},
        "versions": [],
        "current_version": -1,
        "df_cache": {"version": None, "df": None},
        "profile": None,
        "recipe": [],
        "request": {},
        "pending": empty_pending(),
        "result": None,
        "suggestions": [],
        "attachments": {},  # second files for joins: name -> {filename, format, encoding, data_path, shape, columns}
        "chat": empty_chat(),  # assistant messages + token usage; DELETE /chat resets it
    }


def create_upload_flow():
    """Detect -> Read -> v0 -> Profile -> Suggest. Errors end in BuildErrorNode."""
    detect, read, save = DetectFormatNode(), ReadFileNode(), SaveVersionNode()
    profile, suggest, error = ProfileNode(), SuggestNode(), BuildErrorNode()
    detect >> read >> save >> profile >> suggest
    detect - "error" >> error
    read - "error" >> error
    return Flow(start=detect)


def create_operation_flow():
    """One button press. Inspect ops skip saving; transform ops save a new version."""
    resolve, load, execute = ResolveOperationNode(), LoadCurrentDataNode(), ExecuteOperationNode()
    save, profile, suggest = SaveVersionNode(), ProfileNode(), SuggestNode()
    build, error = BuildResultNode(), BuildErrorNode()

    resolve - "invalid" >> error
    resolve - "inspect" >> load
    resolve - "transform" >> load
    load >> execute
    execute - "error" >> error
    execute - "inspect_done" >> build
    execute - "preview_done" >> build
    execute - "transform_done" >> save
    save >> profile >> suggest >> build
    return Flow(start=resolve)


def create_move_flow():
    """Undo / redo / checkout: move the pointer, reload, re-profile."""
    move, load, profile, suggest, error = MoveVersionNode(), LoadCurrentDataNode(), ProfileNode(), SuggestNode(), BuildErrorNode()
    move >> load >> profile >> suggest
    move - "error" >> error
    return Flow(start=move)


def create_export_flow():
    load = LoadCurrentDataNode()
    load >> WriteExportNode()
    return Flow(start=load)


def create_script_flow():
    return Flow(start=GenerateScriptNode())


def create_chat_flow():
    """Agent: decide -> (button or sandboxed code through the operation flow) -> record -> decide ... -> answer."""
    start, decide, request, record, answer = ChatStartNode(), DecideActionNode(), ToolRequestNode(), ToolResultNode(), ChatAnswerNode()
    start >> decide
    decide - "tool" >> request
    request >> create_operation_flow() >> record
    record - "decide" >> decide
    decide - "answer" >> answer
    return Flow(start=start)


def create_attach_flow():
    """Read a second file (for joins) into shared["attachments"]."""
    return Flow(start=AttachFileNode())


class RecipeStepsBatch(BatchFlow):
    """One run of the per-step flow per recipe step, in order (each step needs the previous result)."""

    def prep(self, shared):
        return [{"step_index": i} for i in range(len(shared["replay"]["steps"]))]


def create_replay_flow():
    """Validate -> [step -> operation flow -> record] per step -> report -> reload + profile."""
    step, record = ReplayStepNode(), RecordStepNode()
    step >> create_operation_flow() >> record
    step - "skip" >> Node()  # a previous step failed: end this iteration quietly
    batch = RecipeStepsBatch(start=step)

    validate, report, error = ValidateRecipeNode(), ReplayReportNode(), BuildErrorNode()
    load, profile, suggest = LoadCurrentDataNode(), ProfileNode(), SuggestNode()
    validate - "error" >> error
    validate >> batch >> report >> load >> profile >> suggest
    return Flow(start=validate)
