import os
import sys
from pathlib import Path

os.environ["WB_FAKE"] = "1"          # tests never touch the network
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
