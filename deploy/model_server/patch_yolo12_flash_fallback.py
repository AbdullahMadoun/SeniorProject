from __future__ import annotations

import shutil
import sys
from pathlib import Path


IMPORT_OLD = (
    "try:\n"
    "    from flash_attn.flash_attn_interface import flash_attn_func\n"
    "except Exception:\n"
    "    assert False, \"import FlashAttention error! Please install FlashAttention first.\"\n"
    "from timm.models.layers import trunc_normal_\n"
)

IMPORT_NEW = (
    "import logging\n"
    "logger = logging.getLogger(__name__)\n\n"
    "USE_FLASH_ATTN = False\n"
    "try:\n"
    "    import torch\n"
    "    if torch.cuda.is_available() and torch.cuda.get_device_capability()[0] >= 8:\n"
    "        from flash_attn.flash_attn_interface import flash_attn_func\n"
    "        USE_FLASH_ATTN = True\n"
    "    else:\n"
    "        from torch.nn.functional import scaled_dot_product_attention as sdpa\n"
    "        logger.warning(\"FlashAttention is not available on this device. Using scaled_dot_product_attention instead.\")\n"
    "except Exception:\n"
    "    from torch.nn.functional import scaled_dot_product_attention as sdpa\n"
    "    logger.warning(\"FlashAttention is not available on this device. Using scaled_dot_product_attention instead.\")\n"
    "from timm.models.layers import trunc_normal_\n"
)

ATTN_OLD = (
    "        if x.is_cuda:\n"
    "            x = flash_attn_func(\n"
    "                q.contiguous().half(),\n"
    "                k.contiguous().half(),\n"
    "                v.contiguous().half()\n"
    "            ).to(q.dtype)\n"
    "        else:\n"
    "            q = q.permute(0, 2, 3, 1)\n"
    "            k = k.permute(0, 2, 3, 1)\n"
    "            v = v.permute(0, 2, 3, 1)\n"
    "            attn = (q.transpose(-2, -1) @ k) * (self.head_dim ** -0.5)\n"
    "            max_attn = attn.max(dim=-1, keepdim=True).values \n"
    "            exp_attn = torch.exp(attn - max_attn)\n"
    "            attn = exp_attn / exp_attn.sum(dim=-1, keepdim=True)\n"
    "            x = (v @ attn.transpose(-2, -1))\n"
    "            x = x.permute(0, 3, 1, 2)\n"
    "            v = v.permute(0, 3, 1, 2)\n"
)

ATTN_NEW = (
    "        if x.is_cuda and USE_FLASH_ATTN:\n"
    "            x = flash_attn_func(\n"
    "                q.contiguous().half(),\n"
    "                k.contiguous().half(),\n"
    "                v.contiguous().half()\n"
    "            ).to(q.dtype)\n"
    "        else:\n"
    "            q = q.permute(0, 2, 3, 1)\n"
    "            k = k.permute(0, 2, 3, 1)\n"
    "            v = v.permute(0, 2, 3, 1)\n"
    "            attn = (q.transpose(-2, -1) @ k) * (self.head_dim ** -0.5)\n"
    "            max_attn = attn.max(dim=-1, keepdim=True).values\n"
    "            exp_attn = torch.exp(attn - max_attn)\n"
    "            attn = exp_attn / exp_attn.sum(dim=-1, keepdim=True)\n"
    "            x = (v @ attn.transpose(-2, -1))\n"
    "            x = x.permute(0, 3, 1, 2)\n"
    "            v = v.permute(0, 3, 1, 2)\n"
)


def patch_repo(repo_dir: Path) -> None:
    block_path = repo_dir / "ultralytics" / "nn" / "modules" / "block.py"
    if not block_path.exists():
        raise SystemExit(f"missing block.py at {block_path}")

    text = block_path.read_text(encoding="utf-8")
    if "USE_FLASH_ATTN = False" in text and "scaled_dot_product_attention" in text:
        print(f"already patched {block_path}")
        return

    backup = block_path.with_suffix(".py.bak_flash_fallback")
    if not backup.exists():
        shutil.copy2(block_path, backup)

    if IMPORT_OLD in text:
        text = text.replace(IMPORT_OLD, IMPORT_NEW, 1)
    else:
        raise SystemExit("import block pattern not found in YOLO12 fork")

    if ATTN_OLD in text:
        text = text.replace(ATTN_OLD, ATTN_NEW, 1)
    else:
        raise SystemExit("attention block pattern not found in YOLO12 fork")

    block_path.write_text(text, encoding="utf-8")
    print(f"patched {block_path}")
    print(f"backup {backup}")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: patch_yolo12_flash_fallback.py <yolo12_repo_dir>", file=sys.stderr)
        return 1
    patch_repo(Path(argv[1]).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
