import sys
import os
sys.path.append("/root/road_inspector")
try:
    from main import init_models, get_engine
    print("Import successful")
    print(f"get_engine: {get_engine}")
    init_models()
    print("init_models successful")
except Exception as e:
    import traceback
    traceback.print_exc()
