#!/bin/sh
### PatchTST pretraining + evaluation job — DTU HPC
###
### Submit from repo root:
###     bsub < ml/models/patch_tst/hpc_patchtst.sh
###
### Monitor:
###     bstat               — job status
###     bpeek <jobid>       — live stdout
###     cat logs/pretrain_<jobid>.out

### ─── queue ────────────────────────────────────────────────────────────────
#BSUB -q gpuv100

### ─── job name ────────────────────────────────────────────────────────────
#BSUB -J patchtst-pretrain

### ─── cores ───────────────────────────────────────────────────────────────
# 4 CPU cores on the same host — used by DataLoader workers
#BSUB -n 4
#BSUB -R "span[hosts=1]"

### ─── GPU ─────────────────────────────────────────────────────────────────
#BSUB -gpu "num=1:mode=exclusive_process"

### ─── memory ──────────────────────────────────────────────────────────────
# 16 GB per core = 64 GB total; no -M to avoid the 5% cap rule
#BSUB -R "rusage[mem=16GB]"

### ─── walltime ────────────────────────────────────────────────────────────
# 20k cohort: 16M train windows/epoch. batch 1024 → ~16k steps/epoch.
# 40 epochs + stride-1 test eval can run long; 24 h gives headroom.
#BSUB -W 24:00

### ─── email notifications ─────────────────────────────────────────────────
#BSUB -u furlanettoguido@gmail.com
#BSUB -B
#BSUB -N

### ─── output files (overwrite on resubmission) ───────────────────────────
#BSUB -oo logs/pretrain_%J.out
#BSUB -eo logs/pretrain_%J.err

# ── end of LSF options ─────────────────────────────────────────────────────

### ─── environment ────────────────────────────────────────────────────────
module load python3/3.10.12
module load cuda/12.1

source .venv/bin/activate

### ─── sanity checks ─────────────────────────────────────────────────────
echo "Job ID:   $LSB_JOBID"
echo "Host:     $(hostname)"
echo "GPU:      $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo 'n/a')"
echo "Python:   $(python --version)"
echo "Started:  $(date)"
echo "-----"

mkdir -p logs ml/data/checkpoints

### ─── 1. pretraining ────────────────────────────────────────────────────
# num_workers=4: the dataset is plain numpy arrays now, so forked workers
# share memory copy-on-write without duplicating it
# Flags pinned explicitly so this script is the run's reproducibility record:
# per-patient z-score, fixed seed, val capped at 800 patients for fast
# checkpoint selection. batch 1024 (tiny model underutilises the V100 at 256);
# lr 2e-4 compensates for the ~4x fewer gradient updates per epoch.
echo "=== PRETRAINING ==="
python ml/models/patch_tst/pretrain.py \
    --epochs        40  \
    --batch_size    1024 \
    --lr            2e-4 \
    --num_workers   4 \
    --norm          per_patient \
    --seed          42 \
    --val_patients  800 \
    || { echo "Pretraining failed — skipping evaluation"; exit 1; }

### ─── 2. evaluation ─────────────────────────────────────────────────────
# Runs immediately after training on the same GPU allocation.
# --norm MUST match pretraining. Glucose-only score, 20-min prediction horizon.
echo ""
echo "=== EVALUATION ==="
python ml/models/patch_tst/anomaly_score.py \
    --checkpoint     ml/data/checkpoints/patchtst_best.pt \
    --batch_size     512 \
    --num_workers    4 \
    --norm           per_patient \
    --score_channels 0 \
    --horizon_patches 1

echo "-----"
echo "Finished: $(date)"
