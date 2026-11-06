"""Dataset versions on disk, one pickle per version.

Pickle instead of parquet: parquet rejects mixed-type columns (for example a numeric
column filled with the text 'Unknown'), and every step must be storable.
The files are written and read only by this server, never taken from users.
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def save_version(storage_dir, version, df):
    folder = Path(storage_dir) / "versions"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"v{version}.pkl"
    df.to_pickle(path)
    logger.info("Saved version %s shape=%s", version, df.shape)
    return str(path)


def load_version(path):
    return pd.read_pickle(path)


def delete_versions(paths):
    for path in paths:
        Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    import tempfile

    folder = tempfile.mkdtemp()
    saved = save_version(folder, 0, pd.DataFrame({"a": [1, "x"]}))
    assert load_version(saved)["a"].tolist() == [1, "x"]
    delete_versions([saved])
    assert not Path(saved).exists()
    print("version_store ok")
