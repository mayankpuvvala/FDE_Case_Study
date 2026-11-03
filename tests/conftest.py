import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mmm.generator import GenConfig, generate, write_csvs  # noqa: E402


@pytest.fixture(scope="session")
def ds():
    return generate(GenConfig(seed=3))


@pytest.fixture(scope="session")
def data_dir(ds, tmp_path_factory):
    d = tmp_path_factory.mktemp("refresh")
    write_csvs(ds, d)
    return d
