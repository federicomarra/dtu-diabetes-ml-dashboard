#!/bin/sh
### XCHANNEL EVAL-ONLY job - DTU HPC
###
### Scores an EXISTING checkpoint (no retraining). Use after pretraining has
### produced ml/data/checkpoints/xchannel_best.pt.
###
### Submit from repo root:
###     bsub < ml/models/xchannel/hpc_xchannel_eval.sh

#BSUB -q gpuv100
#BSUB -J xchannel-eval
#BSUB -n 4
#BSUB -R "span[hosts=1]"
#BSUB -gpu "num=1:mode=exclusive_process"
#BSUB -R "rusage[mem=16GB]"
# stride-5 single-pass eval ~ 5-10 min; 2 h is ample.
#BSUB -W 2:00
#BSUB -u furlanettoguido@gmail.com
#BSUB -B
#BSUB -N
#BSUB -oo logs/xchannel_eval_%J.out
#BSUB -eo logs/xchannel_eval_%J.err

module load python3/3.10.12
module load cuda/12.1
source .venv/bin/activate

echo "Job ID:   $LSB_JOBID"
echo "Host:     $(hostname)"
echo "GPU:      $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo 'n/a')"
echo "Started:  $(date)"
echo "-----"

mkdir -p logs

echo "=== EVALUATION (existing checkpoint) ==="
python ml/models/xchannel/anomaly_score.py \
    --checkpoint   ml/data/checkpoints/xchannel_best.pt \
    --batch_size   512 \
    --num_workers  0 \
    --norm         per_patient \
    --test_stride  5

echo "-----"
echo "Finished: $(date)"
