import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from hupa_eval.split import hupa_split  # noqa: E402

PIDS = [f"HUPA{i:04d}P" for i in range(1, 26)]   # 25 patients


def test_split_sizes_disjoint_deterministic():
    a = hupa_split(PIDS); b = hupa_split(PIDS)
    assert a == b                                            # deterministic
    assert (len(a["train"]), len(a["val"]), len(a["test"])) == (15, 3, 7)
    allp = a["train"] + a["val"] + a["test"]
    assert sorted(allp) == sorted(PIDS) and len(set(allp)) == 25   # disjoint, full cover


def test_eval_proxy_filter_selects_split():
    from types import SimpleNamespace
    cohort = [SimpleNamespace(pid=p) for p in PIDS]
    sel = set(hupa_split(PIDS)["test"])
    filt = [p for p in cohort if p.pid in sel]
    assert len(filt) == 7 and {p.pid for p in filt} == sel


def test_labelled_render_excludes_anomaly_windows():
    from hupa_eval.train_on_real import labelled_render
    from characterization.rules import RuleConfig
    from models.xchannel.dataset import ForecastWindowDataset
    from hupa_eval.adapter import load_hupa_cohort
    p = load_hupa_cohort()[0]
    arr = labelled_render(p, RuleConfig(), 30.0, 30)
    assert arr.shape[1] == 8
    n_all = len(ForecastWindowDataset([p.pid], _preloaded={p.pid: arr.copy()},
                                      stride=15, train_on="all")._starts)
    n_norm = len(ForecastWindowDataset([p.pid], _preloaded={p.pid: arr},
                                       stride=15, train_on="normal")._starts)
    assert n_norm <= n_all                              # flagged windows excluded
