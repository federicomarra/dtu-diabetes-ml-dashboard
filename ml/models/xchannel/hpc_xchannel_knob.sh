#!/bin/sh
### XCHANNEL-NLL twin-cohort retrain + transfer eval - realism knob #1
###
### Trains the SAME XCHANNEL-NLL forecaster on the knob-ON vs knob-OFF sim cohort
### (per-patient therapy heterogeneity), then evaluates each
### zero-shot on the sim test set + all three real datasets (Ohio / Manchester / HUPA).
### knob-ON vs knob-OFF transfer delta = does widening the sim cohort help real-data
### detection? Per the diagnosis: expect HUPA-side gains at best, likely no Ohio move.
###
### Submit TWICE - pass KNOB through with -env (plain `KNOB=off bsub <` is ignored):
###     bsub -env "all, KNOB=on"  < ml/models/xchannel/hpc_xchannel_knob.sh
###     bsub -env "all, KNOB=off" < ml/models/xchannel/hpc_xchannel_knob.sh

#BSUB -q gpuv100
#BSUB -J xchannel-knob
#BSUB -n 4
#BSUB -R "span[hosts=1]"
#BSUB -gpu "num=1:mode=exclusive_process"
#BSUB -R "rusage[mem=16GB]"
#BSUB -W 16:00
#BSUB -u furlanettoguido@gmail.com
#BSUB -B
#BSUB -N
#BSUB -oo logs/xchannel_knob_%J.out
#BSUB -eo logs/xchannel_knob_%J.err

module load python3/3.10.12
module load cuda/12.1
source .venv/bin/activate

KNOB="${KNOB:-on}"
# glob the cohort: filename carries the generator job id (..._knobon_<jobid>.parquet),
# but there is exactly one knob{on,off} cohort in sim_data - match it without pinning the id.
PARQUET=$(ls ml/data/sim_data/results_2000p_42d_knob${KNOB}_*.parquet 2>/dev/null | head -1)
CKPT="ml/data/checkpoints/xchannel_nll_knob${KNOB}_best.pt"

echo "Job ID:   $LSB_JOBID"
echo "Host:     $(hostname)"
echo "KNOB:     $KNOB"
echo "Parquet:  $PARQUET"
echo "Started:  $(date)"
echo "-----"
mkdir -p logs ml/data/checkpoints

if [ ! -f "$PARQUET" ]; then echo "MISSING cohort parquet: $PARQUET"; exit 1; fi

echo "=== PRETRAINING (knob=$KNOB, probabilistic NLL) ==="
python ml/models/xchannel/pretrain.py \
    --epochs        40 \
    --batch_size    512 \
    --lr            2e-4 \
    --stride        15 \
    --num_workers   4 \
    --train_on      normal \
    --norm          per_patient \
    --seed          42 \
    --val_patients  400 \
    --parquet       "$PARQUET" \
    --probabilistic \
    --tag           "knob${KNOB}" \
    || { echo "Pretraining failed - skipping evaluation"; exit 1; }

echo ""
echo "=== EVAL on sim test set (knob=$KNOB cohort) ==="
python ml/models/xchannel/anomaly_score.py \
    --checkpoint "$CKPT" --batch_size 512 --num_workers 0 \
    --norm per_patient --parquet "$PARQUET" --test_stride 5

for DS in ohio manchester hupa; do
    echo ""
    echo "=== TRANSFER EVAL: knob=$KNOB -> $DS (cleaned proxy labels) ==="
    python ml/ohio_eval/eval_proxy.py \
        --dataset "$DS" --checkpoint "$CKPT" --features raw --clean --score sym \
        || echo "  eval on $DS FAILED"
done

echo "-----"
echo "Finished: $(date)"
