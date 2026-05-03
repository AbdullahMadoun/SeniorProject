# Senior Project Model Evaluation

## Executive Summary

The completed benchmark achieved the intended system tradeoff: we gave up strict exact-image matching in order to maximize **Damage Coverage Recall**, which is the safety-critical objective for this project.

In practical terms, the final tuned 4-YOLO ensemble moved the system from a best single-model test coverage of **70.15%** to a fused test coverage of **88.06%**. That gain came from accepting many more extra boxes, which drove strict exact-image-match to **0.00%** at the ensemble level. This is an acceptable trade because the downstream workflow can absorb false positives, while missed damage is the failure mode that matters most.

This brief is based on the completed benchmark artifacts and a regenerated report run from `training_pilot/build_benchmark_report.py` against the archived workspace snapshot under `artifacts/training_pilot_sync/2026-04-11/`.

## Base 4-Model Validation Benchmark

The table below compares the original four benchmark members on the validation split. Ranking is recall-first, with `damage_coverage_recall` treated as the primary decision metric.

| Model | Precision | Detector Recall | mAP@0.5 | mAP@0.5:0.95 | Damage Coverage Recall | All Damage Found Rate | Exact Image Match Rate | Predictions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `yolov8m_custom_benchmark` | 50.62% | 53.23% | 51.85% | 27.18% | **66.13%** | **44.44%** | **16.67%** | 154 |
| `yolov8s_diverse` | 36.73% | 24.19% | 24.56% | 8.75% | 62.90% | 44.44% | 0.00% | 597 |
| `yolov8l_custom_benchmark` | 60.21% | 38.71% | 49.67% | 23.53% | 59.68% | 38.89% | 11.11% | 143 |
| `yolo12s_custom_benchmark` | **67.58%** | 35.48% | 40.87% | 22.03% | 54.84% | 38.89% | 5.56% | 98 |

Interpretation:

- `yolov8m_custom_benchmark` was the strongest standalone detector for the project objective.
- `yolo12s_custom_benchmark` was the cleanest detector by precision, but it under-covered the ground-truth damage set.
- `yolov8s_diverse` added useful error diversity for fusion, even though it was not a good standalone deployment target.

## Hardware Deployment Candidate

### `yolov8m_custom_benchmark_plus8` as the Raspberry Pi Candidate

For edge-style deployment, the only realistic option is a single detector. In this benchmark, the deployment candidate is **`yolov8m_custom_benchmark_plus8`**.

Its headline result is **64.18% test Damage Coverage Recall**, which keeps a meaningful share of the safety benefit while remaining a single-model path. This is materially below the ensemble ceiling, but it is the only candidate that remains plausible for Raspberry Pi deployment.

| Candidate | Basis | Precision | mAP@0.5 | mAP@0.5:0.95 | Damage Coverage Recall | All Damage Found Rate | Exact Image Match Rate | Predictions |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `yolov8m_custom_benchmark_plus8` | Best checkpoint validation metrics + final test coverage | 60.98% | 57.20% | 30.29% | **64.18%** | 35.00% | 5.00% | 139 |

Technical note:

- The precision and mAP values above come from the saved `best.pt` checkpoint validation metrics embedded in the continuation checkpoint.
- The recall, all-found rate, exact-match rate, and prediction count come from the saved test coverage artifact.

## Theoretical Ceiling: 4-YOLO Ensemble

### Tuned `_skip04` Multiscale Ensemble

The theoretical safety ceiling of the completed work is the tuned **4-YOLO multiscale ensemble with `skip_box_thr = 0.04`**.

This system is not a Raspberry Pi target. It is the cloud-grade, quality-first reference configuration. Its value is that algorithmic fusion substantially reduces missed damage by combining complementary error patterns from four detectors and multiple test-time views.

| Configuration | Split | Damage Coverage Recall | All Damage Found Rate | Exact Image Match Rate | Predictions | Matched GT / Total GT |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 4-YOLO practical TTA baseline | Validation | 80.65% | 50.00% | 0.00% | 440 | 50 / 62 |
| 4-YOLO multiscale + flip TTA | Validation | 88.71% | 66.67% | 0.00% | 785 | 55 / 62 |
| 4-YOLO tuned multiscale `_skip04` | Validation | **90.32%** | **66.67%** | 0.00% | 1089 | 56 / 62 |
| 4-YOLO tuned multiscale `_skip04` | Test | **88.06%** | **65.00%** | 0.00% | 1242 | 59 / 67 |

Interpretation:

- Fusion added a large safety margin over any single detector.
- The tuned `_skip04` ensemble improved validation coverage from **66.13%** for the best base single model to **90.32%**.
- On test, the same configuration held **88.06%** coverage, confirming that the recall gain was not just a validation artifact.
- Exact-image-match dropped to zero because the fused system intentionally preserved borderline detections instead of pruning aggressively.

## Side-by-Side System Comparison

The table below shows the systems that matter most for decision-making: the best original single model, the selected Raspberry Pi candidate, and the final cloud ensemble.

| System | Deployment Class | Precision | mAP@0.5 | Damage Coverage Recall | All Damage Found Rate | Exact Image Match Rate | Predictions |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `yolov8m_custom_benchmark` | Single model, benchmark winner | 50.62% | 51.85% | 70.15% test | 40.00% test | 0.00% test | 178 |
| `yolov8m_custom_benchmark_plus8` | Single model, Raspberry Pi candidate | **60.98%** | **57.20%** | 64.18% test | 35.00% test | 5.00% test | **139** |
| 4-YOLO tuned multiscale `_skip04` ensemble | Cloud reference ceiling | N/A | N/A | **88.06% test** | **65.00% test** | 0.00% test | 1242 |

Key takeaway:

- If the objective is **edge deployment**, select `yolov8m_custom_benchmark_plus8`.
- If the objective is **maximum safety coverage**, select the tuned 4-YOLO ensemble.

## Final Recommendation

The project now has a clear two-tier deployment story.

For constrained hardware, carry forward **`yolov8m_custom_benchmark_plus8`** as the single-model deployment candidate. It preserves a useful level of damage coverage with a much smaller prediction volume than the cloud ensemble and retains solid detector precision and mAP.

For cloud or server-side inference, the final answer is the **tuned 4-YOLO multiscale `_skip04` ensemble**. It is the highest-recall configuration produced in the completed benchmark and should be treated as the system safety ceiling for the current generation of the project.

## Artifact Basis

- Regenerated report bundle: `artifacts/training_pilot_sync/2026-04-11/final_export/artifacts/reporting_val_regen/`
- Archived report bundle: `artifacts/training_pilot_sync/2026-04-11/final_export/artifacts/reporting_val/`
- Continuation coverage artifacts:
  - `artifacts/training_pilot_sync/2026-04-11/final_export/artifacts/yolov8m_plus8_val_coverage.json`
  - `artifacts/training_pilot_sync/2026-04-11/final_export/artifacts/yolov8m_plus8_test_coverage.json`
  - `artifacts/training_pilot_sync/2026-04-11/final_export/artifacts/ensemble_4yolo_plus8_multiscale_val_skip04.json`
  - `artifacts/training_pilot_sync/2026-04-11/final_export/artifacts/ensemble_4yolo_plus8_multiscale_test_skip04.json`
