#!/bin/sh
### XCHANNEL (temporal patching) pretraining + evaluation — DTU HPC
###
### Quality-program Step 1: lift the near-linear 3-token ceiling with per-channel
### temporal patch tokens (patch_len=20 → ~22 tokens, 3 layers). Same task/loss
### as hpc_xchannel.sh; only the architecture changes, for clean attribution.
###
### Submit from repo root:
###     bsub < ml/models/xchannel/hpc_xchannel_patched.sh

#BSUB -q gpuv100
#BSUB -J xchannel-patched
#BSUB -n 4
#BSUB -R "span[hosts=1]"
#BSUB -gpu "num=1:mode=exclusive_process"
#BSUB -R "rusage[mem=16GB]"
#BSUB -W 24:00
#BSUB -u furlanettoguido@gmail.com
#BSUB -B
#BSUB -N
#BSUB -oo logs/xchannel_patched_%J.out
#BSUB -eo logs/xchannel_patched_%J.err

module load python3/3.10.12
module load cuda/12.1
source .venv/bin/activate

echo "Job ID:   $LSB_JOBID"
echo "Host:     $(hostname)"
echo "GPU:      $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo 'n/a')"
echo "Started:  $(date)"
echo "-----"
mkdir -p logs ml/data/checkpoints

echo "=== PRETRAINING (patch_len=20, n_layers=3) ==="
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
    --patch_len     20 \
    --n_layers      3 \
    || { echo "Pretraining failed — skipping evaluation"; exit 1; }

echo ""
echo "=== EVALUATION (simulator test set) ==="
python ml/models/xchannel/anomaly_score.py \
    --checkpoint   ml/data/checkpoints/xchannel_patched_best.pt \
    --batch_size   512 \
    --num_workers  0 \
    --norm         per_patient \
    --test_stride  5

echo "-----"
echo "Finished: $(date)"
