"""Pooled HUPA+Ohio real cohort + stratified split (pooled-transfer experiment).

Ohio = 12 unique patients (TRAIN-split records,
~40 d each - one record per patient, no leakage); HUPA = 25. HUPA pids (HUPA0001P)
and Ohio pids (numeric 540) are disjoint -> filter by pid membership, no tagging.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from hupa_eval.adapter import load_hupa_cohort      # noqa: E402
from ohio_eval.adapter import load_ohio_cohort      # noqa: E402
from realdata.manchester_adapter import load_manchester_cohort  # noqa: E402

OHIO_ROOT = Path("ml/data/real/ohio")


def load_pooled(ohio_root: Path = OHIO_ROOT):
    """Return ({pid: patient}, hupa_pids, ohio_pids, manchester_pids). Ohio = train-split
    (12 unique). HUPA/Ohio/Manchester pid ranges are disjoint (HUPA0001P / 540 / 2301)."""
    hu = load_hupa_cohort()
    oh = load_ohio_cohort(ohio_root, year="both", split="train")   # 12 unique, longest records
    man = load_manchester_cohort()                                  # 13 usable (all 4 streams)
    cohort: dict = {}
    for grp in (hu, oh, man):
        for p in grp:
            assert p.pid not in cohort, f"pid collision: {p.pid}"
            cohort[p.pid] = p
    return (cohort, sorted(p.pid for p in hu), sorted(p.pid for p in oh),
            sorted(p.pid for p in man))


def pooled_split(hupa_pids, ohio_pids, manchester_pids=(), seed: int = 42,
                 n_hupa_test: int = 7, n_ohio_test: int = 4, n_man_test: int = 4,
                 n_val: int = 6) -> dict:
    """Stratified patient-level split: reserve test per dataset (single-cohort test
    sets), pool the remainder, carve val. Deterministic per seed."""
    rng = np.random.default_rng(seed)

    def shuf(pids):
        pids = sorted(pids)
        idx = rng.permutation(len(pids))
        return [pids[i] for i in idx]

    hu, oh, man = shuf(hupa_pids), shuf(ohio_pids), shuf(manchester_pids)
    hupa_test, ohio_test, man_test = hu[:n_hupa_test], oh[:n_ohio_test], man[:n_man_test]
    tv = shuf(hu[n_hupa_test:] + oh[n_ohio_test:] + man[n_man_test:])
    return {"train": tv[n_val:], "val": tv[:n_val],
            "test": hupa_test + ohio_test + man_test,
            "hupa_test": hupa_test, "ohio_test": ohio_test, "manchester_test": man_test}
