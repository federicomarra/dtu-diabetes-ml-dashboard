#!/bin/sh
### XCHANNEL (probabilistic / NLL + sensor-artifact augmentation) - DTU HPC
###
### Step 2 of the sensor-artifact work: train with on-the-fly dropouts/jumps/
### compression on the TRAIN split (val stays clean) so the detector stops
### false-firing on sensor artifacts. Step-1 stress test showed the base model
### flags 70% of artifact windows (sim) / 36% (Ohio) vs ~9-14% clean baseline.
### Evaluation here is the clean sim-test (sanity); the artifact ABLATION is run
### separately with ml/ohio_eval/eval_artifact_stress.py on base vs this ckpt.
###
### Submit from repo root:
###     bsub < ml/models/xchannel/hpc_xchannel_nll_aug.sh

#BSUB -q gpuv100
#BSUB -J xchannel-nll-aug
#BSUB -n 4
#BSUB -R "span[hosts=1]"
#BSUB -gpu "num=1:mode=exclusive_process"
#BSUB -R "rusage[mem=16GB]"
#BSUB -W 24:00
#BSUB -u furlanettoguido@gmail.com
#BSUB -B
#BSUB -N
#BSUB -oo logs/xchannel_nll_aug_%J.out
#BSUB -eo logs/xchannel_nll_aug_%J.err

module load python3/3.10.12
module load cuda/12.1
source .venv/bin/activate

echo "Job ID:   $LSB_JOBID"
echo "Host:     $(hostname)"
echo "GPU:      $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo 'n/a')"
echo "Started:  $(date)"
echo "-----"
mkdir -p logs ml/data/checkpoints

echo "=== PRETRAINING (probabilistic NLL + sensor-artifact augmentation, train-only) ==="
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
    --augment \
    || { echo "Pretraining failed - skipping evaluation"; exit 1; }

echo ""
echo "=== EVALUATION (simulator test set, clean - sanity that augmentation didn't hurt) ==="
python ml/models/xchannel/anomaly_score.py \
    --checkpoint   ml/data/checkpoints/xchannel_nll_aug_best.pt \
    --batch_size   512 \
    --num_workers  0 \
    --norm         per_patient \
    --parquet      ml/data/sim_data/results_5000p_42d.parquet \
    --test_stride  5

echo "-----"
echo "Finished: $(date)"
