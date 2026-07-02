#!/bin/sh
### XCHANNEL (IOB/COB features) pretraining + evaluation — DTU HPC
###
### Same model as hpc_xchannel.sh but inputs are IOB/COB (insulin/carbs-on-board,
### ml/features/iob_cob.py) instead of raw insulin/carb rates. Encoding-robust →
### the generalization ("B") arm of the OhioT1DM A→B contrast.
###
### Submit from repo root:
###     bsub < ml/models/xchannel/hpc_xchannel_iobcob.sh

#BSUB -q gpuv100
#BSUB -J xchannel-iobcob
#BSUB -n 4
#BSUB -R "span[hosts=1]"
#BSUB -gpu "num=1:mode=exclusive_process"
#BSUB -R "rusage[mem=16GB]"
#BSUB -W 24:00
#BSUB -u furlanettoguido@gmail.com
#BSUB -B
#BSUB -N
#BSUB -oo logs/xchannel_iobcob_%J.out
#BSUB -eo logs/xchannel_iobcob_%J.err

module load python3/3.10.12
module load cuda/12.1
source .venv/bin/activate

echo "Job ID:   $LSB_JOBID"
echo "Host:     $(hostname)"
echo "GPU:      $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo 'n/a')"
echo "Started:  $(date)"
echo "-----"

mkdir -p logs ml/data/checkpoints

echo "=== PRETRAINING (IOB/COB features) ==="
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
    --features      iob_cob \
    || { echo "Pretraining failed — skipping evaluation"; exit 1; }

echo ""
echo "=== EVALUATION (simulator test set, IOB/COB) ==="
python ml/models/xchannel/anomaly_score.py \
    --checkpoint   ml/data/checkpoints/xchannel_iobcob_best.pt \
    --batch_size   512 \
    --num_workers  0 \
    --norm         per_patient \
    --test_stride  5 \
    --features     iob_cob

echo "-----"
echo "Finished: $(date)"
