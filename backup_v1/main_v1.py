import asyncio
import logging
from pathlib import Path

from flow import create_process_flow, create_shared, create_upload_flow
from utils.artifact_exporter import pd_sample


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    session_id = "demo-session"
    upload_dir = Path("uploads")
    upload_dir.mkdir(exist_ok=True)
    raw_path = upload_dir / f"{session_id}_raw.csv"
    pd_sample().to_csv(raw_path, index=False)

    shared = create_shared(session_id, str(raw_path), advisor_mode="heuristic")
    asyncio.run(create_upload_flow().run_async(shared))
    print("Suggested target:", shared["cleaning_config"]["target_column"])
    print("Suggested drops:", shared["cleaning_config"]["drop_columns"])

    create_process_flow().run(shared)
    report = shared["final_report"]
    print("Train shape:", report["train_shape"])
    print("Test shape:", report["test_shape"])
    print("Nulls remaining:", report["total_nulls_remaining"])
    print("All numeric:", report["all_numeric_verified"])
    print("Train CSV:", report["train_csv_url"])


if __name__ == "__main__":
    main()
