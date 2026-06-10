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
# 20k cohort: ~73k contrastive steps/epoch × 30 epochs could reach 5–6 h,
# plus GMM fitting + stride-1 test scoring ≈ 1 h. 12 h gives headroom.
#BSUB -W 12:00

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

# Flags pinned explicitly so this script is the run's reproducibility record.
# NB: supervised oracle-negative CARLA (uses simulator labels) — see CARLA.md.
echo "=== CARLA PRETRAINING ==="
python ml/models/carla/pretrain.py \
    --epochs        30  \
    --batch_size   256  \
    --lr           1e-4 \
    --tau          0.07 \
    --normal_ratio 0.7 \
    --norm         per_patient \
    --seed         42 \
    || { echo "Pretraining failed — skipping evaluation"; exit 1; }

### ─── 2. evaluation ─────────────────────────────────────────────────────
# --norm MUST match pretraining. --gmm_sample caps the GMM fit (default 300k).
echo ""
echo "=== CARLA EVALUATION ==="
python ml/models/carla/anomaly_score.py \
    --checkpoint  ml/data/checkpoints/carla_best.pt \
    --norm        per_patient \
    --gmm_sample  300000

echo "-----"
echo "Finished: $(date)"
