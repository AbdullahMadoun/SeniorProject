from __future__ import annotations

import argparse
import importlib
import shutil
import sys
from pathlib import Path
from typing import Any

from common import dump_json, load_pipeline_config, resolve_project_root

try:
    import torch
except Exception:  # noqa: BLE001
    torch = None

if torch is not None and not hasattr(torch, "OutOfMemoryError"):
    cuda_oom = getattr(getattr(torch, "cuda", None), "OutOfMemoryError", RuntimeError)
    torch.OutOfMemoryError = cuda_oom

SPATIAL_TRANSFORMS = {
    "Affine",
    "BBoxSafeRandomCrop",
    "CenterCrop",
    "CoarseDropout",
    "Crop",
    "CropAndPad",
    "CropNonEmptyMaskIfExists",
    "D4",
    "ElasticTransform",
    "Flip",
    "GridDistortion",
    "GridDropout",
    "HorizontalFlip",
    "Lambda",
    "LongestMaxSize",
    "MaskDropout",
    "MixUp",
    "Morphological",
    "NoOp",
    "OpticalDistortion",
    "PadIfNeeded",
    "Perspective",
    "PiecewiseAffine",
    "PixelDropout",
    "RandomCrop",
    "RandomCropFromBorders",
    "RandomGridShuffle",
    "RandomResizedCrop",
    "RandomRotate90",
    "RandomScale",
    "RandomSizedBBoxSafeCrop",
    "RandomSizedCrop",
    "Resize",
    "Rotate",
    "SafeRotate",
    "ShiftScaleRotate",
    "SmallestMaxSize",
    "Transpose",
    "VerticalFlip",
    "XYMasking",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train one directive-aligned model in a backend-isolated process.")
    parser.add_argument("--project-root", default="")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--stage", choices=["initial", "hard_negative"], default="initial")
    parser.add_argument("--data-yaml", default="")
    return parser.parse_args()


def resolve_model_entry(config: dict[str, Any], model_id: str) -> dict[str, Any]:
    for entry in config.get("models", []):
        if entry["id"] == model_id:
            return entry
    raise KeyError(f"Unknown model id: {model_id}")


def inject_backend_path(project_root: Path, model_entry: dict[str, Any]) -> None:
    backend = model_entry["backend"]
    if backend == "ultralytics":
        return
    repo_dir = model_entry.get("repo_dir")
    if not repo_dir:
        raise RuntimeError(f"Model {model_entry['id']} is missing repo_dir for backend '{backend}'")
    target = (project_root / repo_dir).resolve()
    if not target.exists():
        raise FileNotFoundError(f"Missing backend repo dir for {model_entry['id']}: {target}")
    sys.path.insert(0, str(target))


def install_custom_albumentations(project_root: Path, pipeline: dict[str, Any]) -> None:
    transforms_cfg = pipeline.get("albumentations", [])
    if not transforms_cfg:
        return

    augment = importlib.import_module("ultralytics.data.augment")
    import albumentations as A

    class CustomAlbumentations:
        def __init__(self, p: float = 1.0, transforms: list | None = None) -> None:
            self.p = p
            self.transform = None
            prefix = augment.colorstr("albumentations: ")
            try:
                import os

                os.environ["NO_ALBUMENTATIONS_UPDATE"] = "1"
                augment.check_version(A.__version__, "1.0.3", hard=True)
                transform_list = []
                for item in transforms_cfg:
                    kwargs = dict(item.get("args", {}))
                    kwargs["p"] = float(item["p"])
                    transform_cls = getattr(A, item["name"])
                    transform_list.append(transform_cls(**kwargs))
                self.contains_spatial = any(t.__class__.__name__ in SPATIAL_TRANSFORMS for t in transform_list)
                self.transform = (
                    A.Compose(transform_list, bbox_params=A.BboxParams(format="yolo", label_fields=["class_labels"]))
                    if self.contains_spatial
                    else A.Compose(transform_list)
                )
                if hasattr(self.transform, "set_random_seed"):
                    self.transform.set_random_seed(augment.torch.initial_seed())
                augment.LOGGER.info(prefix + ", ".join(f"{x}".replace("always_apply=False, ", "") for x in transform_list))
            except Exception as exc:
                augment.LOGGER.info(f"{prefix}{exc}")
                raise

        def __call__(self, labels: dict[str, Any]) -> dict[str, Any]:
            if self.transform is None or augment.random.random() > self.p:
                return labels
            image = labels["img"]
            if image.shape[2] != 3:
                return labels
            if self.contains_spatial:
                cls = labels["cls"]
                if len(cls):
                    labels["instances"].convert_bbox("xywh")
                    labels["instances"].normalize(*image.shape[:2][::-1])
                    bboxes = labels["instances"].bboxes
                    transformed = self.transform(image=image, bboxes=bboxes, class_labels=cls)
                    if len(transformed["class_labels"]) > 0:
                        labels["img"] = transformed["image"]
                        labels["cls"] = augment.np.array(transformed["class_labels"]).reshape(-1, 1)
                        bboxes = augment.np.array(transformed["bboxes"], dtype=augment.np.float32)
                    labels["instances"].update(bboxes=bboxes)
            else:
                labels["img"] = self.transform(image=labels["img"])["image"]
            return labels

    augment.Albumentations = CustomAlbumentations


def load_yolo_class(model_entry: dict[str, Any], project_root: Path, pipeline: dict[str, Any]):
    inject_backend_path(project_root, model_entry)
    from ultralytics import YOLO

    install_custom_albumentations(project_root, pipeline)
    return YOLO


def build_train_kwargs(
    pipeline: dict[str, Any],
    model_entry: dict[str, Any],
    project_root: Path,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], str]:
    training = pipeline["training"]
    stage = args.stage
    if args.data_yaml:
        data_yaml = Path(args.data_yaml).resolve()
    else:
        if stage == "hard_negative":
            data_yaml = project_root / "configs" / "dataset_hard_negatives.yaml"
        else:
            configured_data_yaml = training.get("data_yaml") or pipeline.get("dataset", {}).get("data_yaml", "")
            data_yaml = (project_root / configured_data_yaml).resolve() if configured_data_yaml else (project_root / "configs" / "dataset.yaml")

    if not data_yaml.exists():
        raise FileNotFoundError(f"Missing dataset yaml for stage '{stage}': {data_yaml}")

    base_run_name = str(model_entry.get("run_name", model_entry["id"]))
    run_name = base_run_name if stage == "initial" else f"{base_run_name}_hard_negative"
    epochs = int(model_entry["epochs"])
    lr0 = float(model_entry["lr0"])
    freeze = int(model_entry["freeze"])
    if stage == "hard_negative":
        second_pass = training["second_pass"]
        if second_pass.get("epochs") is None:
            raise RuntimeError(
                "Second-pass epoch count is not locked yet. "
                "Update configs/max_recall/pipeline.yaml -> training.second_pass.epochs before running 05_second_pass_train.sh."
            )
        epochs = int(second_pass["epochs"])
        lr0 = float(model_entry["lr0"]) * float(second_pass["lr_scale"])
        freeze = int(second_pass["freeze"])

    batch_value = model_entry["batch"]
    if isinstance(batch_value, str):
        numeric = float(batch_value)
        batch_value = int(numeric) if numeric.is_integer() else numeric
    elif isinstance(batch_value, float) and batch_value.is_integer():
        batch_value = int(batch_value)

    kwargs = {
        "data": str(data_yaml),
        "epochs": epochs,
        "imgsz": int(training["imgsz"]),
        "batch": batch_value,
        "lr0": lr0,
        "freeze": freeze,
        "patience": int(model_entry["patience"]),
        "weight_decay": float(model_entry["weight_decay"]),
        "optimizer": training["optimizer"],
        "cos_lr": bool(training["cos_lr"]),
        "amp": bool(training["amp"]),
        "single_cls": bool(training["single_cls"]),
        "deterministic": bool(training["deterministic"]),
        "box": float(training["box"]),
        "cls": float(training["cls"]),
        "device": args.device,
        "workers": args.workers,
        "project": str((project_root / "runs").resolve()),
        "name": run_name,
        "save": True,
        "val": True,
        "plots": True,
        "exist_ok": False,
    }

    optional_training_fields: dict[str, Any] = {
        "conf": training.get("val_conf"),
        "dfl": training.get("dfl"),
        "lrf": training.get("lrf"),
        "momentum": training.get("momentum"),
        "warmup_epochs": training.get("warmup_epochs"),
        "warmup_momentum": training.get("warmup_momentum"),
        "close_mosaic": training.get("close_mosaic"),
        "mosaic": training.get("mosaic"),
        "mixup": training.get("mixup"),
        "copy_paste": training.get("copy_paste"),
        "erasing": training.get("erasing"),
        "label_smoothing": training.get("label_smoothing"),
        "degrees": training.get("degrees"),
        "translate": training.get("translate"),
        "scale": training.get("scale"),
        "flipud": training.get("flipud"),
        "fliplr": training.get("fliplr"),
        "cache": training.get("cache"),
        "save_period": training.get("save_period"),
        "seed": training.get("seed"),
    }
    kwargs.update({key: value for key, value in optional_training_fields.items() if value is not None})
    return kwargs, run_name


def copy_finetuned_weights(run_dir: Path, finetuned_dir: Path, model_id: str) -> dict[str, str]:
    target_dir = finetuned_dir / model_id
    target_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for name in ("best.pt", "last.pt"):
        source = run_dir / "weights" / name
        if source.exists():
            dest = target_dir / name
            shutil.copy2(source, dest)
            outputs[name] = str(dest.resolve())
    return outputs


def main() -> None:
    args = parse_args()
    project_root = resolve_project_root(args.project_root or None)
    pipeline = load_pipeline_config(project_root)
    model_entry = resolve_model_entry(pipeline, args.model_id)
    pretrained_path = (project_root / model_entry["pretrained"]).resolve()
    if not pretrained_path.exists():
        raise FileNotFoundError(f"Missing pretrained checkpoint for {args.model_id}: {pretrained_path}")

    YOLO = load_yolo_class(model_entry, project_root, pipeline)
    kwargs, run_name = build_train_kwargs(pipeline, model_entry, project_root, args)
    model = YOLO(str(pretrained_path))
    results = model.train(**kwargs)
    save_dir = Path(getattr(model.trainer, "save_dir"))
    finetuned_dir = (project_root / pipeline["weights"]["finetuned_dir"]).resolve()
    copied = copy_finetuned_weights(save_dir, finetuned_dir, args.model_id)

    record = {
        "model_id": args.model_id,
        "stage": args.stage,
        "backend": model_entry["backend"],
        "pretrained": str(pretrained_path),
        "run_dir": str(save_dir.resolve()),
        "results_csv": str((save_dir / "results.csv").resolve()),
        "weights": copied,
        "train_kwargs": kwargs,
        "results_type": type(results).__name__,
    }
    dump_json(project_root / "artifacts" / "training" / f"{run_name}.json", record)
    print(record)


if __name__ == "__main__":
    main()
