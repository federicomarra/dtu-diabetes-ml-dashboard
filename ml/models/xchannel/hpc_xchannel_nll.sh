#!/bin/sh
### XCHANNEL (probabilistic / NLL) pretraining + evaluation - DTU HPC
###
### Quality-program Step 2: predict mean+variance, train with Gaussian NLL, score
### anomalies by surprise-under-uncertainty (residual / predicted sigma). Targets the
### over-detection of the point-MSE score WITHOUT adding forecasting capacity
### (Step 1 showed capacity doesn't help). 3-token model (patching was dropped).
###
### Submit from repo root:
###     bsub < ml/models/xchannel/hpc_xchannel_nll.sh

#BSUB -q gpuv100
#BSUB -J xchannel-nll
#BSUB -n 4
#BSUB -R "span[hosts=1]"
#BSUB -gpu "num=1:mode=exclusive_process"
#BSUB -R "rusage[mem=16GB]"
#BSUB -W 24:00
#BSUB -u furlanettoguido@gmail.com
#BSUB -B
#BSUB -N
#BSUB -oo logs/xchannel_nll_%J.out
#BSUB -eo logs/xchannel_nll_%J.err

module load python3/3.10.12
module load cuda/12.1
source .venv/bin/activate

echo "Job ID:   $LSB_JOBID"
echo "Host:     $(hostname)"
echo "GPU:      $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo 'n/a')"
echo "Started:  $(date)"
echo "-----"
mkdir -p logs ml/data/checkpoints

echo "=== PRETRAINING (probabilistic, Gaussian NLL) ==="
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
    --parquet       ml/data/sim_data/results_5000p_42d.parquet \
    --probabilistic \
    || { echo "Pretraining failed - skipping evaluation"; exit 1; }

echo ""
echo "=== EVALUATION (simulator test set) ==="
python ml/models/xchannel/anomaly_score.py \
    --checkpoint   ml/data/checkpoints/xchannel_nll_best.pt \
    --batch_size   512 \
    --num_workers  0 \
    --norm         per_patient \
    --parquet      ml/data/sim_data/results_5000p_42d.parquet \
    --test_stride  5

echo "-----"
echo "Finished: $(date)"
