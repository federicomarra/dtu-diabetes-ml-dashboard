#!/bin/sh
### CARLA contrastive pretraining + evaluation job — DTU HPC
###
### Submit from repo root:
###     bsub < ml/models/carla/hpc_carla.sh
###
### Monitor:
###     bstat               — job status
###     bpeek <jobid>       — live stdout
###     cat logs/carla_<jobid>.out

### ─── queue ────────────────────────────────────────────────────────────────
#BSUB -q gpuv100

### ─── job name ────────────────────────────────────────────────────────────
#BSUB -J carla-pretrain

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
# 30 epochs ≈ 2–3 h + GMM fitting + evaluation ≈ 30 min; 8 h is safe
#BSUB -W 8:00

### ─── email notifications ─────────────────────────────────────────────────
#BSUB -u furlanettoguido@gmail.com
#BSUB -B
#BSUB -N

### ─── output files (overwrite on resubmission) ───────────────────────────
#BSUB -oo logs/carla_%J.out
#BSUB -eo logs/carla_%J.err

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
echo "=== CARLA PRETRAINING ==="
python ml/models/carla/pretrain.py \
    --epochs        30  \
    --batch_size   256  \
    --lr           1e-4 \
    --tau          0.07 \
    --normal_ratio 0.7

### ─── 2. evaluation ─────────────────────────────────────────────────────
echo ""
echo "=== CARLA EVALUATION ==="
python ml/models/carla/anomaly_score.py \
    --checkpoint ml/data/checkpoints/carla_best.pt

echo "-----"
echo "Finished: $(date)"
