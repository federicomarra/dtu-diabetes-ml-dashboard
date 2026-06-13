"""
Evaluate the characterization head on the simulator test set.

Reports the honesty-aware metrics from INSTRUCTIONS §289–297:
  * per-class recall + overall balanced accuracy (similarity quality on sim)
  * MC-Dropout uncertainty (mean predictive std) per class
  * latent-OOD separation (Mahalanobis distance: normal vs anomaly windows)

On real data the same head produces soft "resembles X 72%" + OOD; here we score
it where labels exist (sim) to characterise its behaviour honestly.

Usage
-----
    python ml/characterization/eval_head.py --smoke_test --parquet ml/data/sim_data/results_500p_14d_clean.parquet
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).parent.parent))
from dataset import make_patient_split, ANOMALY_CLASSES  # noqa: E402
from models.xchannel.model import forecaster_from_ckpt  # noqa: E402
from models.xchannel.dataset import ForecastWindowDataset  # noqa: E402
from characterization.head import CharacterizationHead, mc_predict, ood_distance, CLASSES, N_CLASSES  # noqa: E402
from characterization.train_head import _batch_classes  # noqa: E402

CHECKPOINT_DIR = Path("ml/data/checkpoints")


@torch.no_grad()
def main():
    p = argparse.ArgumentParser(description="Eval characterization head on sim")
    p.add_argument("--head", type=Path, default=CHECKPOINT_DIR / "characterization_head.pt")
    p.add_argument("--parquet", type=Path, default=Path("ml/data/sim_data/results_20000p_14d.parquet"))
    p.add_argument("--stride", type=int, default=30)
    p.add_argument("--batch_size", type=int, default=512)
    p.add_argument("--n_patients", type=int, default=400)
    p.add_argument("--mc_passes", type=int, default=30)
    p.add_argument("--smoke_test", action="store_true")
    args = p.parse_args()
    if args.smoke_test:
        args.n_patients, args.mc_passes = 40, 10

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    hk = torch.load(args.head, map_location=device)
    feats = hk["features"]
    encoder = forecaster_from_ckpt(torch.load(hk["xchannel_checkpoint"], map_location=device), device)
    encoder.eval()
    head = CharacterizationHead().to(device); head.load_state_dict(hk["head_state"]); head.eval()
    mu, inv_cov = np.asarray(hk["ood_mu"]), np.asarray(hk["ood_inv_cov"])
    print(f"Head on frozen XCHANNEL (features={feats})")

    ids = make_patient_split(args.parquet)["test"][: args.n_patients]
    ds = ForecastWindowDataset(ids, parquet=args.parquet, stride=args.stride,
                               train_on="all", features=feats)
    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=False)

    n_cls = N_CLASSES
    conf = np.zeros((n_cls, n_cls), dtype=np.int64)     # [true, pred]
    unc_sum = np.zeros(n_cls); ood_sum = np.zeros(n_cls); seen = np.zeros(n_cls)
    for glu, ins, carb, _t, labels in loader:
        z = encoder(glu.to(device), ins.to(device), carb.to(device), return_embeddings=True)
        probs, unc = mc_predict(head, z, args.mc_passes)
        pred = probs.argmax(-1).cpu().numpy()
        true = _batch_classes(labels)
        dist = ood_distance(z.cpu().numpy(), mu, inv_cov)
        for t, pr, u, d in zip(true, pred, unc.cpu().numpy(), dist):
            conf[t, pr] += 1; unc_sum[t] += u; ood_sum[t] += d; seen[t] += 1

    print(f"\n  {'class':<11} {'n':>7} {'recall':>7} {'MC-unc':>8} {'OOD-dist':>9}")
    recalls = []
    for c in range(n_cls):
        if seen[c] == 0:
            continue
        rec = conf[c, c] / seen[c]; recalls.append(rec)
        print(f"  {CLASSES[c]:<11} {int(seen[c]):>7} {rec:>7.3f} "
              f"{unc_sum[c]/seen[c]:>8.4f} {ood_sum[c]/seen[c]:>9.2f}")
    print(f"\n  balanced accuracy (mean recall): {np.mean(recalls):.3f}  | chance {1/n_cls:.3f}")
    print(f"  OOD check: anomaly windows should sit FARTHER from the normal cluster than normal.")


if __name__ == "__main__":
    main()
