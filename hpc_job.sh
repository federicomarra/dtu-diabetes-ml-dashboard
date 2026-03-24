#!/bin/sh
### DTU HPC Job Script
### Supports both API backend and ML training workloads

### ─── LSF Options ─────────────────────────────────────────
#BSUB -J diabetes-ml
#BSUB -q hpc
#BSUB -W 24:00
#BSUB -R "rusage[mem=8GB]"
#BSUB -n 4
#BSUB -o logs/job_%J.out
#BSUB -e logs/job_%J.err

### Uncomment for GPU jobs (ML training):
# #BSUB -q gpuv100
# #BSUB -gpu "num=1:mode=exclusive_process"
# #BSUB -R "rusage[mem=16GB]"

### ─── Environment Setup ──────────────────────────────────
module load python3/3.10.12

# Uncomment for GPU jobs:
# module load cuda/12.1
# module load cudnn/8.9.5

# Create / activate virtual environment
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

### ─── Mode Selection ─────────────────────────────────────
MODE=${1:-api}  # Default: run API server. Pass 'train' for ML training.

case $MODE in
    api)
        echo "Starting API server..."
        cd backend
        pip install -r requirements.txt --quiet
        flask db upgrade  # Apply migrations
        gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 120 wsgi:app
        ;;

    train)
        echo "Starting ML training..."
        cd ml
        pip install -r requirements.txt --quiet
        python training/train_anomaly.py
        ;;

    generate)
        echo "Generating synthetic data..."
        cd ml
        pip install -r requirements.txt --quiet
        python data/generate_synthetic.py
        ;;

    seed)
        echo "Seeding database..."
        cd backend
        pip install -r requirements.txt --quiet
        cd ..
        python database/seed.py
        ;;

    *)
        echo "Unknown mode: $MODE"
        echo "Usage: bsub < hpc_job.sh [api|train|generate|seed]"
        exit 1
        ;;
esac