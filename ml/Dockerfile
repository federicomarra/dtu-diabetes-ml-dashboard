FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default: generate synthetic data
CMD ["python", "data/generate_synthetic.py"]
