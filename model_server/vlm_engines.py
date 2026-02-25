import torch
from abc import ABC, abstractmethod
from typing import Any, Optional, Union, List
from PIL import Image
from transformers import AutoProcessor, AutoModelForCausalLM, BitsAndBytesConfig
from vllm import LLM, SamplingParams
import textwrap

class VLMEngine(ABC):
    @abstractmethod
    def generate(self, image: Image.Image, prompt: str, system_prompt: str) -> str:
        pass

    @abstractmethod
    def cleanup(self):
        """Release resources and clear VRAM."""
        pass

class QwenEngine(VLMEngine):
    def __init__(self, model_name: str, gpu_util: float, max_len: int, processor: AutoProcessor):
        self.model_name = model_name
        self.processor = processor
        
        quantization = None
        if "-AWQ" in model_name.upper():
            quantization = "awq"
        elif "-GPTQ" in model_name.upper():
            quantization = "gptq"
            
        print(f"[VLM] Initializing LLM with model={model_name}, gpu_util={gpu_util}, max_len={max_len}, quantization={quantization}")
        self.engine = LLM(
            model=model_name,
            gpu_memory_utilization=gpu_util,
            max_model_len=max_len,
            trust_remote_code=True,
            dtype="half",
            quantization=quantization,

            max_num_seqs=4,
            disable_log_stats=False, # Re-enable stats for debugging
        )
        print(f"[VLM] Engine initialized successfully.")

    def generate(self, image: Image.Image, prompt: str, system_prompt: str) -> str:
        try:
            from qwen_vl_utils import process_vision_info
            
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image},
                        {"type": "text", "text": prompt},
                    ],
                },
            ]
            
            image_inputs, _ = process_vision_info(messages)
            text_prompt = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            
            sampling_params = SamplingParams(
                temperature=0.01,
                top_p=0.3,
                max_tokens=1500,
                repetition_penalty=1.2,
            )
            
            outputs = self.engine.generate(
                [{"prompt": text_prompt, "multi_modal_data": {"image": image_inputs}}],
                sampling_params=sampling_params,
            )
            return outputs[0].outputs[0].text
        except Exception as e:
            import traceback
            print(f"[VLM ERROR] Generation failed: {e}")
            traceback.print_exc()
            raise

    def cleanup(self):
        print(f"[VLM] Cleaning up Qwen engine: {self.model_name}")
        if hasattr(self, 'engine'):
            import gc
            import torch
            del self.engine
            self.engine = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()



def get_vlm_engine(model_type: str, model_name: str, gpu_util: float, max_len: int) -> VLMEngine:
    if model_type.lower() == "qwen":
        processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=True)
        return QwenEngine(model_name, gpu_util, max_len, processor)
    else:
        raise ValueError(f"Unsupported VLM type: {model_type}")
