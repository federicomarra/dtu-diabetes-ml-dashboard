#!/bin/sh
### XCHANNEL pretraining + evaluation job - DTU HPC
###
### Cross-channel conditional glucose forecaster (iTransformer-style).
### Submit from repo root:
###     bsub < ml/models/xchannel/hpc_xchannel.sh
###
### Monitor:
###     bstat ; bpeek <jobid> ; cat logs/xchannel_<jobid>.out

### --- queue ----------------------------------------------------------------
#BSUB -q gpuv100

### --- job name ------------------------------------------------------------
#BSUB -J xchannel-pretrain

### --- cores ---------------------------------------------------------------
#BSUB -n 4
#BSUB -R "span[hosts=1]"

### --- GPU -----------------------------------------------------------------
#BSUB -gpu "num=1:mode=exclusive_process"

### --- memory --------------------------------------------------------------
#BSUB -R "rusage[mem=16GB]"

### --- walltime ------------------------------------------------------------
# Tiny model (459k params), 3 tokens. ~16M train windows/epoch at stride 15,
# batch 512. 40 epochs + stride-5 eval is comfortable; 24 h gives headroom.
#BSUB -W 24:00

### --- email ----------------------------------------------------------------
#BSUB -u furlanettoguido@gmail.com
#BSUB -B
#BSUB -N

### --- output files (overwrite on resubmission) ---------------------------
#BSUB -oo logs/xchannel_%J.out
#BSUB -eo logs/xchannel_%J.err

# -- end of LSF options -----------------------------------------------------

module load python3/3.10.12
module load cuda/12.1
source .venv/bin/activate

echo "Job ID:   $LSB_JOBID"
echo "Host:     $(hostname)"
echo "GPU:      $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo 'n/a')"
echo "Python:   $(python --version)"
echo "Started:  $(date)"
echo "-----"

mkdir -p logs ml/data/checkpoints

### --- 1. pretraining ----------------------------------------------------
# Pinned for reproducibility: clean-windows-only training (model learns normal
# dynamics), per-patient z-score, fixed seed, val capped at 800 patients.
echo "=== PRETRAINING ==="
python ml/models/xchannel/pretrain.py \
    --epochs        40 \
    --batch_size    512 \
    --lr            2e-4 \
    --stride        15 \
    --num_workers   4 \
    --train_on      normal \
    --norm          per_patient \
    --seed          42 \
    --val_patients  800 \
    || { echo "Pretraining failed - skipping evaluation"; exit 1; }

### --- 2. evaluation -----------------------------------------------------
# --norm MUST match pretraining. num_workers 0 avoids the DataLoader worker
# deadlock that froze the PatchTST eval on a many-million-window test set.
# --test_stride 5: 16M windows, ~same AUPRC as stride 1 at 5x less compute.
echo ""
echo "=== EVALUATION ==="
python ml/models/xchannel/anomaly_score.py \
    --checkpoint   ml/data/checkpoints/xchannel_best.pt \
    --batch_size   512 \
    --num_workers  0 \
    --norm         per_patient \
    --test_stride  5

echo "-----"
echo "Finished: $(date)"
