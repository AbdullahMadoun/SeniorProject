# Frontend Integration Guide: Road Inspector API

This guide provides frontend developers with the necessary details to integrate the latest version of the Road Inspector API. The API has been updated to use a strict, safety-focused hazard classification model.

## 1. API Endpoint Overview

- **Endpoint**: `POST /analyze`
- **Headers**: 
  - `Content-Type: application/json`
  - `X-API-Key: <your-api-key>`

## 2. Request Format

The API accepts a base64 encoded image and an **optional** location field. The location field is highly flexible.

```json
{
  "image_b64": "base64_string_here...",
  
  // OPTION 1: Object format (Recommended)
  "location": {"lat": 26.3073, "lon": 50.1456},
  
  // OPTION 2: Array format (Handy for mapping libraries)
  // "location": [26.3073, 50.1456],
  
  // OPTION 3: Omitted entirely (No location data available)
  // (Do not send the "location" key)
}
```

## 3. Response Format

The API returns a JSON object containing the `report`. 

```json
{
  "report": {
    "summary": "2 defect(s) detected. 1 high-severity issue(s) requiring immediate attention.",
    "boxes": [
      {
        "id": "D0",
        "class": "pothole",
        "label": "Pothole",
        "bbox_xyxy": [120, 300, 450, 500],
        "severity": "high"
      },
      {
        "id": "D1",
        "class": "crack",
        "label": "Longitudinal Crack",
        "bbox_xyxy": [500, 600, 520, 800],
        "severity": "low"
      }
    ],
    "report_markdown": "# Pavement Distress Repair Report\n\n## 1) Scene context...\n"
  }
}
```

## 4. Feature Parsing Guidelines

**A. Severity Mapping (Hazard Classification)**
The new model explicitly maps to exactly one of three string values for `severity`. The frontend should map these to distinct visual warnings:
*   `"low"`: (Green/Blue) Minor hazard, monitor over time.
*   `"moderate"`: (Yellow/Orange) Noticeable hazard, schedule repair.
*   `"high"`: (Red) Immediate safety hazard to vulnerable road users (e.g., motorcycles). Render with prominent alerts or badges.

**B. Bounding Boxes (`bbox_xyxy`)**
Bounding boxes are returned in absolute pixel coordinates mapping to the original uploaded image sequence: `[x_min, y_min, x_max, y_max]`.
*   You must scale these coordinates if you render the image at a different size in the DOM.
*   *Formula*: `rendered_x = x_min * (rendered_width / original_image_width)`

**C. The Human-Readable Report (`report_markdown`)**
The `report_markdown` string contains a highly detailed, formatted engineering report meant for field crews. 
*   **Do not** attempt to string parse or regex this field for logic. 
*   Use a trusted Markdown renderer (like `react-markdown` or `marked`) to display this directly in a "View Full Report" modal or tab.

## 5. Error Handling

- **401/403**: Invalid or missing `X-API-Key`.
- **400**: Malformed base64 image or invalid JSON structure.
- **422**: Validation error (e.g., passing a location array with 3 numbers instead of 2).
- **500**: Inference failure (Rare, generally vLLM engine timeouts). Implement a standard retry geometry.
