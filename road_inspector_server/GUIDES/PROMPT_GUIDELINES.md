# Prompt Handling Guidelines: Safety-Focused Classification

The road inspection API now uses the customized, safety-first prompt located in `/root/prompt.txt`. This update replaces subjective analysis with strict, observable hazard classifications.

## Key Changes Introduced by the New Prompt:
1. **Simplified JSON Output:** The VLM will strictly output only two keys:
    - `"report_markdown"` (A formatted report intended for human technicians)
    - `"severities"` (A dictionary mapping each defect ID to exactly one of `low`, `moderate`, or `high`)
2. **Deterministic Rules:**
    - The model no longer attempts to guess precise measurements in mm/cm.
    - Severity is solely calculated based on the immediate danger posed to vulnerable road users (e.g., motorcycles or cyclists).
    - If a defect appears shallow or the model is uncertain, it defaults to `low` or `moderate`. `high` is reserved exclusively for deep craters or significant breakup visually confirmed in the image.
3. **API Alignment:** The `main.py` parsing logic natively handles this two-key structure, injecting the `"severities"` block back into the returned bounding box telemetry.

## Guidelines for Downstream Systems:
- **Do not rely on the `report_markdown` for automated logic.** It is strictly designed for human readability (crew-ready). 
- **Rely on the structured JSON `boxes` list** returned by the API for your database insertion and analysis. Every detection in the `boxes` list will inherently have a `severity` attached, derived directly from the VLM JSON dict.
- **Fail-Safes:** If the image is heavily obscured, the prompt is instructed to fall back to `moderate` for visible defects to avoid classifying unseen hazards as harmless. Handle `moderate` defects with a schedule for physical field verification.
