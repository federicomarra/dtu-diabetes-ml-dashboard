#!/bin/sh
### Characterization head - train + eval on DTU HPC
###
### Trains the similarity head on the FROZEN XCHANNEL encoder (sim labels), then
### evaluates per-class recall / MC-uncertainty / OOD on the sim test set.
### Needs a trained XCHANNEL checkpoint (xchannel_best.pt) already present.
###
### Submit from repo root:
###     bsub < ml/characterization/hpc_char_head.sh

#BSUB -q gpuv100
#BSUB -J char-head
#BSUB -n 4
#BSUB -R "span[hosts=1]"
#BSUB -gpu "num=1:mode=exclusive_process"
#BSUB -R "rusage[mem=16GB]"
#BSUB -W 4:00
#BSUB -u furlanettoguido@gmail.com
#BSUB -B
#BSUB -N
#BSUB -oo logs/char_head_%J.out
#BSUB -eo logs/char_head_%J.err

module load python3/3.10.12
module load cuda/12.1
source .venv/bin/activate

echo "Job ID:   $LSB_JOBID"
echo "Host:     $(hostname)"
echo "Started:  $(date)"
echo "-----"
mkdir -p logs ml/data/checkpoints

### features MUST match the XCHANNEL checkpoint used (raw -> xchannel_best.pt).
echo "=== TRAIN characterization head ==="
python ml/characterization/train_head.py \
    --features       raw \
    --epochs         30 \
    --n_patients     2000 \
    --max_per_class  20000 \
    --num_workers    4 \
    --seed           42 \
    || { echo "Head training failed"; exit 1; }

echo ""
echo "=== EVAL characterization head (sim test) ==="
python ml/characterization/eval_head.py --n_patients 400 --mc_passes 30

echo "-----"
echo "Finished: $(date)"
