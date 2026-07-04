"""
Combined inference path - the "clinical diary".

Ties the three pieces together for one patient:

    1. XCHANNEL detector: per-window forecast-residual anomaly score
    2. per-patient robust threshold (median + 2*IQR/1.349 on baseline)
    3. flagged windows grouped into EVENTS (start, duration)
    4. for each event:
         - rule classifier: deterministic label (missed/late/large) IF inputs logged
         - similarity head: soft "resembles X 72%" + MC-Dropout uncertainty + latent-OOD

Two claims are kept strictly separate:
  * DETECTION  generalises   - "unusual for this patient vs their baseline"
  * CHARACTERISATION limited - "resembles missed bolus (72%)", a similarity to
    synthetic archetypes, NOT a diagnosis; OOD-flagged "uncharacterised" when the
    window is far from the normal cluster.

`build_diary` is a pure function (models passed in) so it is unit-testable; the
CLI at the bottom loads real checkpoints and prints a diary for an Ohio patient.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, overload

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).parent.parent))
from dataset import N_CHANNELS  # noqa: E402
from features.iob_cob import to_iob_cob  # noqa: E402
from models.xchannel.model import CONTEXT_LEN, HORIZON, anomaly_score as compute_score  # noqa: E402
from models.patch_tst.anomaly_score import calibrate_threshold  # noqa: E402
from characterization.head import mc_predict, ood_distance, CLASSES  # noqa: E402
from characterization.rules import classify_meals, RuleConfig  # noqa: E402

L, H, WIN = CONTEXT_LEN, HORIZON, CONTEXT_LEN + HORIZON
MERGE_GAP_MIN = 30          # flagged windows within this gap -> one event


@dataclass
class Event:
    start_min: int
    duration_min: int
    anomaly_score: float
    soft_label: str                      # top similarity class
    class_probs: dict                    # {class: prob}
    mc_uncertainty: float
    ood_distance: float
    ood_flag: bool                       # True -> far from normal cluster
    characterised: bool = True           # False -> label withheld (OOD / normal / low-conf)
    rule_label: str | None = None        # deterministic, when inputs logged

    def to_text(self) -> str:
        if self.rule_label:                               # deterministic, leads
            label = f"{self.rule_label} (rule)"
        elif self.characterised:                          # humble similarity
            label = f"~{self.soft_label} ({self.class_probs[self.soft_label]:.0%})"
        else:                                             # gated: don't force a class
            label = "uncharacterised"
        return (f"t+{self.start_min}min  dur={self.duration_min}min  "
                f"score={self.anomaly_score:.3f}  | {label}  unc={self.mc_uncertainty:.3f}")


@torch.no_grad()
def _score_windows(arr, valid, detector, device, stride):
    """Per valid window: start minute, forecast residual, encoder embedding."""
    T = arr.shape[0]
    z = arr[:, :N_CHANNELS]
    starts = [s for s in range(0, T - WIN + 1, stride) if valid[s : s + WIN].all()]
    if not starts:
        return [], np.empty(0), np.empty((0, 128))
    scores, embs = [], []
    for i in range(0, len(starts), 512):
        ch = starts[i : i + 512]
        glu = torch.stack([torch.from_numpy(z[s : s + L, 0].copy()) for s in ch]).to(device)
        ins = torch.stack([torch.from_numpy(z[s : s + WIN, 1].copy()) for s in ch]).to(device)
        car = torch.stack([torch.from_numpy(z[s : s + WIN, 2].copy()) for s in ch]).to(device)
        tgt = torch.stack([torch.from_numpy(z[s + L : s + WIN, 0].copy()) for s in ch]).to(device)
        scores.append(compute_score(detector(glu, ins, car), tgt).cpu().numpy())
        embs.append(detector(glu, ins, car, return_embeddings=True).cpu().numpy())
    return starts, np.concatenate(scores), np.concatenate(embs)


def _group_events(flagged_starts):
    """Merge flagged window starts into [first, last] groups (gap <= MERGE_GAP_MIN)."""
    if not flagged_starts:
        return []
    groups, cur = [], [flagged_starts[0]]
    for s in flagged_starts[1:]:
        if s - cur[-1] <= MERGE_GAP_MIN:
            cur.append(s)
        else:
            groups.append(cur); cur = [s]
    groups.append(cur)
    return groups


@overload
def build_diary(arr, valid, *, detector, head, ood_mu, ood_inv_cov, ood_radius=..., features=...,
                meals=..., boluses=..., device=..., stride=..., n_cal_days=..., threshold_k=...,
                min_event_min=..., min_confidence=..., mc_passes=..., rule_cfg=...,
                return_scores: Literal[False] = ...) -> list[Event]: ...
@overload
def build_diary(arr, valid, *, detector, head, ood_mu, ood_inv_cov, ood_radius=..., features=...,
                meals=..., boluses=..., device=..., stride=..., n_cal_days=..., threshold_k=...,
                min_event_min=..., min_confidence=..., mc_passes=..., rule_cfg=...,
                return_scores: Literal[True]) -> tuple[list[Event], np.ndarray]: ...
def build_diary(arr, valid, *, detector, head, ood_mu, ood_inv_cov, ood_radius=float("inf"),
                features="raw", meals=None, boluses=None, device=None, stride=5,
                n_cal_days=5, threshold_k=2.0, min_event_min=30, min_confidence=0.30,
                mc_passes=30, rule_cfg=RuleConfig(), return_scores=False):
    """Returns list[Event]; if return_scores=True, returns (events, all_window_scores)
    so callers can map an event's anomaly_score to a per-patient percentile (strength)."""
    device = device or torch.device("cpu")
    feat_arr = to_iob_cob(arr) if features == "iob_cob" else arr

    starts, scores, embs = _score_windows(feat_arr, valid, detector, device, stride)
    if not starts:
        return ([], np.asarray([], dtype=float)) if return_scores else []

    # per-patient robust threshold on the first n_cal_days of (baseline) scores.
    # threshold_k curbs over-detection (higher k -> fewer flags).
    n_cal = min(len(scores), n_cal_days * 1440 // stride)
    thr = calibrate_threshold(scores, n_cal, k=threshold_k)
    flagged = [s for s, sc in zip(starts, scores) if sc > thr]

    # rule-derived meal labels (deterministic), if meals are logged.
    # boluses may be an empty list - that IS the "missed" case - so test for None.
    rule_minutes = classify_meals(meals, boluses or [], rule_cfg) if meals is not None else {}

    pos = {s: i for i, s in enumerate(starts)}
    events: list[Event] = []
    for grp in _group_events(flagged):
        start_min = grp[0] + L                       # anomaly lives in the horizon
        end_min = grp[-1] + WIN
        if end_min - start_min < min_event_min:      # drop short blips -> less over-detection
            continue
        idx = [pos[s] for s in grp]
        emb = torch.from_numpy(embs[idx].mean(0, keepdims=True)).float().to(device)
        probs, unc = mc_predict(head, emb, mc_passes)
        probs = probs[0].cpu().numpy()
        dist = float(ood_distance(embs[idx].mean(0, keepdims=True), ood_mu, ood_inv_cov)[0])

        top = CLASSES[int(probs.argmax())]
        ood_flag = dist > ood_radius
        # withhold the class when far from normal, when it just looks 'normal', or
        # when the head is barely above chance - don't force a clinical-looking label
        characterised = bool((not ood_flag) and (top != "normal") and (probs.max() >= min_confidence))

        rule_label = None
        for cls, mins in rule_minutes.items():
            if any(start_min - WIN <= m <= end_min for m in mins):
                rule_label = cls; break

        events.append(Event(
            start_min=start_min, duration_min=end_min - start_min,
            anomaly_score=float(scores[idx].max()), soft_label=top,
            class_probs={CLASSES[c]: float(probs[c]) for c in range(len(CLASSES))},
            mc_uncertainty=float(unc[0]), ood_distance=dist, ood_flag=ood_flag,
            characterised=characterised, rule_label=rule_label,
        ))
    return (events, np.asarray(scores, dtype=float)) if return_scores else events


# -- CLI demo on an Ohio patient (needs trained detector + head checkpoints) -----

def _cli():
    import argparse
    from ohio_eval.adapter import load_ohio_patient
    from models.xchannel.model import forecaster_from_ckpt
    from characterization.head import CharacterizationHead

    ap = argparse.ArgumentParser(description="Clinical diary for one OhioT1DM patient")
    ap.add_argument("--patient", type=Path, required=True, help="OhioT1DM XML file")
    ap.add_argument("--detector", type=Path, default=Path("ml/data/checkpoints/xchannel_best.pt"))
    ap.add_argument("--head", type=Path, default=Path("ml/data/checkpoints/characterization_head.pt"))
    ap.add_argument("--features", choices=["raw", "iob_cob"], default="raw")
    ap.add_argument("--ood_radius", type=float, default=None, help="override stored OOD radius")
    ap.add_argument("--threshold_k", type=float, default=3.0, help="detection sensitivity (higher = fewer)")
    ap.add_argument("--min_event_min", type=int, default=30, help="drop events shorter than this")
    ap.add_argument("--max_events", type=int, default=20)
    args = ap.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    det = forecaster_from_ckpt(torch.load(args.detector, map_location=device), device); det.eval()
    hk = torch.load(args.head, map_location=device)
    head = CharacterizationHead().to(device); head.load_state_dict(hk["head_state"]); head.eval()
    mu, inv_cov = np.asarray(hk["ood_mu"]), np.asarray(hk["ood_inv_cov"])

    p = load_ohio_patient(args.patient)
    # OOD radius: CLI override -> stored (99th-pct) radius -> fallback heuristic
    radius = (args.ood_radius if args.ood_radius is not None
              else hk.get("ood_radius", _default_radius(mu)))

    arr = np.zeros((p.T, 8), dtype=np.float32)
    arr[:, :N_CHANNELS] = p.render()[:, :N_CHANNELS]
    # per-patient z-score (deployment uses the patient's own stats)
    m, s = arr[:, :N_CHANNELS].mean(0), arr[:, :N_CHANNELS].std(0).clip(1e-8)
    arr[:, :N_CHANNELS] = (arr[:, :N_CHANNELS] - m) / s

    events = build_diary(arr, p.valid, detector=det, head=head, ood_mu=mu, ood_inv_cov=inv_cov,
                         ood_radius=radius, threshold_k=args.threshold_k,
                         min_event_min=args.min_event_min, features=args.features,
                         meals=p.meals, boluses=p.boluses, device=device)
    assert isinstance(events, list)   # no return_scores -> list[Event] (narrows the union)
    print(f"Patient {p.pid}: {len(events)} detected anomaly events")
    print("DETECTION generalises; CHARACTERISATION = similarity to synthetic archetypes, not diagnosis.\n")
    for e in events[: args.max_events]:
        print("  " + e.to_text())


def _default_radius(mu):
    return float(np.sqrt(len(mu)) * 3.0)   # ~3sigma in a chi-like sense; tune at deploy


if __name__ == "__main__":
    _cli()
