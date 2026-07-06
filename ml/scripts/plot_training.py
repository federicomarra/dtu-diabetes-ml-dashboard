"""
Plot PatchTST pretraining loss curves.

Reads ml/data/checkpoints/pretrain_log.json produced by pretrain.py and
saves a train/val loss figure to ml/figures/training_loss.png.

Usage
-----
    python ml/scripts/plot_training.py
    python ml/scripts/plot_training.py --log ml/data/checkpoints/pretrain_log.json
"""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# -- paths ---------------------------------------------------------------------

LOG_PATH    = Path("ml/data/checkpoints/pretrain_log.json")
FIGURES_DIR = Path("ml/figures")


# -- plot ----------------------------------------------------------------------

def plot_loss(log: list[dict], out_path: Path) -> None:
    epochs     = [e["epoch"]      for e in log]
    train_loss = [e["train_loss"] for e in log]
    val_loss   = [e["val_loss"]   for e in log]

    best_epoch = min(log, key=lambda e: e["val_loss"])

    fig, ax = plt.subplots(figsize=(8, 4.5))

    ax.plot(epochs, train_loss, label="Train loss",      color="#2563eb", linewidth=2)
    ax.plot(epochs, val_loss,   label="Val loss (full)", color="#dc2626", linewidth=2)

    # mark best checkpoint
    ax.axvline(
        best_epoch["epoch"], color="#16a34a", linestyle="--", linewidth=1.2,
        label=f"Best checkpoint  (epoch {best_epoch['epoch']}, val={best_epoch['val_loss']:.4f})",
    )

    ax.set_xlabel("Epoch", fontsize=12)
    ax.set_ylabel("MSE loss", fontsize=12)
    ax.set_title("PatchTST pretraining - reconstruction loss", fontsize=13, fontweight="bold")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300)
    plt.close(fig)
    print(f"Saved -> {out_path}")


# -- main ----------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Plot pretraining loss curves")
    parser.add_argument("--log", type=Path, default=LOG_PATH,
                        help="Path to pretrain_log.json")
    parser.add_argument("--out", type=Path, default=FIGURES_DIR / "training_loss.png",
                        help="Output figure path")
    args = parser.parse_args()

    if not args.log.exists():
        raise FileNotFoundError(
            f"Log not found: {args.log}\n"
            "Run pretrain.py first."
        )

    log = json.loads(args.log.read_text())
    print(f"Loaded {len(log)} epochs from {args.log}")
    plot_loss(log, args.out)


if __name__ == "__main__":
    main()
