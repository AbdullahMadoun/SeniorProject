import sys
import os
from PIL import Image
import numpy as np
import io

# Add the project directory to sys.path
sys.path.append("/root/road_inspector")

from vlm_engines import get_vlm_engine
from config import config

def test_engines():
    # Only test Qwen first as CogVLM model is 19B and might take time to download/load
    print("Testing QwenEngine initialization...")
    try:
        # Simulate loading Qwen
        qwen = get_vlm_engine("qwen", config.VLM_MODEL, 0.4, config.VLM_MAX_LEN)
        print("QwenEngine initialized successfully.")
    except Exception as e:
        print(f"QwenEngine failed: {e}")

    # Note: Testing CogVLM might OOM if Qwen is also loaded on a 24GB card
    # We will verify CogVLM by running the API with a single model.

if __name__ == "__main__":
    test_engines()
