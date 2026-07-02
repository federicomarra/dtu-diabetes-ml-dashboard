import sys
from pathlib import Path

# Make `ml/` importable as the root so `from dataset import ...` works
# when pytest is run from the repo root or from ml/tests/.
sys.path.insert(0, str(Path(__file__).parent.parent))
