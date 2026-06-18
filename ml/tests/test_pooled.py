import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from realdata.pooled import pooled_split  # noqa: E402

HU = [f"HUPA{i:04d}P" for i in range(1, 26)]          # 25
OH = ["540", "544", "552", "559", "563", "567", "570", "575", "584", "588", "591", "596"]  # 12


def test_pooled_split_deterministic_stratified_disjoint():
    a = pooled_split(HU, OH); b = pooled_split(HU, OH)
    assert a == b                                                  # deterministic
    assert len(a["hupa_test"]) == 7 and len(a["ohio_test"]) == 4   # stratified test
    assert len(a["test"]) == 11
    allp = a["train"] + a["val"] + a["test"]
    assert sorted(allp) == sorted(HU + OH) and len(set(allp)) == 37  # disjoint, full cover
    assert set(a["hupa_test"]) <= set(HU) and set(a["ohio_test"]) <= set(OH)


def test_pooled_split_seed_varies():
    assert pooled_split(HU, OH, seed=1) != pooled_split(HU, OH, seed=2)
