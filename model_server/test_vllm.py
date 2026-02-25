from vllm import LLM, SamplingParams
import torch

try:
    print("Testing vLLM initialization...")
    llm = LLM(
        model="Qwen/Qwen2.5-VL-7B-Instruct-AWQ",
        quantization="awq",
        dtype="half",
        trust_remote_code=True,
        max_model_len=4096, # Reduced for testing
        gpu_memory_utilization=0.5, # Reduced for testing
    )
    print("Successfully initialized vLLM!")
except Exception as e:
    print(f"Failed to initialize vLLM: {e}")
