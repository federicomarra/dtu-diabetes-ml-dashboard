#!/bin/sh
### PatchTST EVAL-ONLY job - DTU HPC
###
### Scores an EXISTING checkpoint (no retraining). Use after pretraining has
### already produced ml/data/checkpoints/patchtst_best.pt.
###
### Submit from repo root:
###     bsub < ml/models/patch_tst/hpc_patchtst_eval.sh

### --- queue ----------------------------------------------------------------
#BSUB -q gpuv100

### --- job name ------------------------------------------------------------
#BSUB -J patchtst-eval

### --- cores ---------------------------------------------------------------
#BSUB -n 4
#BSUB -R "span[hosts=1]"

### --- GPU -----------------------------------------------------------------
#BSUB -gpu "num=1:mode=exclusive_process"

### --- memory --------------------------------------------------------------
#BSUB -R "rusage[mem=16GB]"

### --- walltime ------------------------------------------------------------
# stride-5 single-pass eval ~ 10-15 min; 2 h is ample.
#BSUB -W 2:00

### --- email ----------------------------------------------------------------
#BSUB -u furlanettoguido@gmail.com
#BSUB -B
#BSUB -N

### --- output files (overwrite on resubmission) ---------------------------
#BSUB -oo logs/patchtst_eval_%J.out
#BSUB -eo logs/patchtst_eval_%J.err

# -- end of LSF options -----------------------------------------------------

module load python3/3.10.12
module load cuda/12.1
source .venv/bin/activate

echo "Job ID:   $LSB_JOBID"
echo "Host:     $(hostname)"
echo "GPU:      $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo 'n/a')"
echo "Started:  $(date)"
echo "-----"

mkdir -p logs

### Eval-only. Cheap + hang-proof:
###   --test_stride 5   80M -> 16M windows (~same AUPRC, windows overlap ~99%)
###   --last_only       skip Option 1 full reconstruction (the weak, costly score)
###   --num_workers 0   no DataLoader worker processes -> no worker deadlock
###   --norm MUST match the pretrain run (per_patient).
echo "=== EVALUATION (existing checkpoint) ==="
python ml/models/patch_tst/anomaly_score.py \
    --checkpoint      ml/data/checkpoints/patchtst_best.pt \
    --batch_size      512 \
    --num_workers     0 \
    --norm            per_patient \
    --score_channels  0 \
    --horizon_patches 1 \
    --test_stride     5 \
    --last_only

echo "-----"
echo "Finished: $(date)"
