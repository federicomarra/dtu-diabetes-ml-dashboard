# ML inference microservice - stateless Flask (detection -> missed/late).
# Build context is the REPO ROOT (so .dockerignore can trim the heavy ml/data):
#     docker build -f ml/Dockerfile -t diabetes-ml .
# or via docker-compose (service `ml`). The model checkpoint is NOT baked in - it is
# mounted read-only at /app/ml/data/checkpoints so the deliverable can be swapped
# without rebuilding.
FROM python:3.10-slim

WORKDIR /app

# CPU-only torch keeps the image lean (~1.5 GB vs ~5 GB with the CUDA wheel) - the
# service runs inference on CPU. Installed before the rest so the requirements pin
# (torch==2.1.2) is already satisfied and not re-resolved from the default index.
COPY ml/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir torch==2.1.2 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt gunicorn==21.2.0

# Code only - ml/data is excluded via .dockerignore and mounted at runtime.
COPY ml/ ./ml/

ENV PYTHONPATH=/app/ml \
    CKPT_DIR=/app/ml/data/checkpoints \
    DETECTOR_CKPT=/app/ml/data/checkpoints/xchannel_nll_pooled_best.pt \
    PORT=5001
EXPOSE 5001

# 1 worker -> the model loads ONCE; long timeout -> inference over multi-day windows
# is not killed mid-request (single-request demo, no queue).
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5001", "--timeout", "300", "inference.service:app"]
