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
# 8 GB per core = 32 GB total; training data alone ~10 GB in RAM
#BSUB -R "rusage[mem=8GB]"
#BSUB -M 12GB

### ─── walltime ────────────────────────────────────────────────────────────
# pretraining 15 epochs ≈ 1–2 h + evaluation ≈ 20 min; 4 h is safe
#BSUB -W 8:00

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
echo "=== PRETRAINING ==="
python ml/models/patch_tst/pretrain.py \
    --epochs      40  \
    --batch_size  256 \
    --lr          1e-4 \
    --num_workers 4

### ─── 2. evaluation ─────────────────────────────────────────────────────
# Runs immediately after training on the same GPU allocation.
# Loads the best checkpoint and prints AUPRC + AUROC per anomaly class.
echo ""
echo "=== EVALUATION ==="
python ml/models/patch_tst/anomaly_score.py \
    --checkpoint ml/data/checkpoints/patchtst_best.pt \
    --batch_size  512 \
    --num_workers 4

echo "-----"
echo "Finished: $(date)"
