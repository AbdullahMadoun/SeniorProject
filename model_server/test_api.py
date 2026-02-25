"""
End-to-end test script for the Road Inspection VLM API.
Sends sample images from the test dataset and validates responses.
"""

import base64
import json
import os
import sys
import time
import glob
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_URL = os.environ.get("API_URL", "http://localhost:17612")
API_KEY = os.environ.get("API_KEY", "road-inspector-secret-key-2024")
TEST_IMAGE_DIR = "/root/test_images/Raw images/RGB main"
OUTPUT_DIR = "/root/road_inspector/test_outputs"
NUM_TEST_IMAGES = 3

os.makedirs(OUTPUT_DIR, exist_ok=True)


def encode_image_file(path: str) -> str:
    """Read an image file and return base64 string."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def save_b64_image(b64_str: str, output_path: str):
    """Decode a base64 image and save to file."""
    img_bytes = base64.b64decode(b64_str)
    with open(output_path, "wb") as f:
        f.write(img_bytes)
    print(f"  [SAVED] {output_path}")


def test_no_api_key():
    """Test that requests without API key are rejected."""
    print("\n" + "=" * 60)
    print("TEST: Request without API key (expect 401)")
    print("=" * 60)

    try:
        resp = requests.post(
            f"{API_URL}/analyze",
            json={
                "image_b64": "dGVzdA==",  # "test" in base64
                "location": {"lat": 26.305, "lon": 50.146},
            },
            timeout=10,
        )
        if resp.status_code in (401, 403):
            print(f"  [PASS] Got expected status: {resp.status_code}")
            return True
        else:
            print(f"  [FAIL] Expected 401/403, got: {resp.status_code}")
            return False
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False


def test_wrong_api_key():
    """Test that requests with wrong API key are rejected."""
    print("\n" + "=" * 60)
    print("TEST: Request with wrong API key (expect 403)")
    print("=" * 60)

    try:
        resp = requests.post(
            f"{API_URL}/analyze",
            json={
                "image_b64": "dGVzdA==",
                "location": {"lat": 26.305, "lon": 50.146},
            },
            headers={"X-API-Key": "wrong-key-12345"},
            timeout=10,
        )
        if resp.status_code in (401, 403):
            print(f"  [PASS] Got expected status: {resp.status_code}")
            return True
        else:
            print(f"  [FAIL] Expected 401/403, got: {resp.status_code}")
            return False
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False


def test_analyze_image(image_path: str, index: int) -> bool:
    """Test the /analyze endpoint with a real image."""
    filename = os.path.basename(image_path)
    print(f"\n{'=' * 60}")
    print(f"TEST {index}: Analyzing {filename}")
    print(f"{'=' * 60}")

    # Encode image
    try:
        image_b64 = encode_image_file(image_path)
        print(f"  [INFO] Image encoded: {len(image_b64)} chars base64")
    except Exception as e:
        print(f"  [FAIL] Could not encode image: {e}")
        return False

    # Send request
    payload = {
        "image_b64": image_b64,
        "location": {"lat": 26.305, "lon": 50.146},  # Al Khobar area
    }

    headers = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

    print(f"  [INFO] Sending request to {API_URL}/analyze ...")
    start_time = time.time()

    try:
        resp = requests.post(
            f"{API_URL}/analyze",
            json=payload,
            headers=headers,
            timeout=300,  # VLM inference can take a while
        )
    except requests.exceptions.Timeout:
        print(f"  [FAIL] Request timed out after 300s")
        return False
    except Exception as e:
        print(f"  [FAIL] Request failed: {e}")
        return False

    elapsed = time.time() - start_time
    print(f"  [INFO] Response received in {elapsed:.1f}s, status: {resp.status_code}")

    if resp.status_code != 200:
        print(f"  [FAIL] Non-200 status: {resp.status_code}")
        print(f"  [FAIL] Response: {resp.text[:500]}")
        return False

    # Parse response
    try:
        data = resp.json()
    except Exception as e:
        print(f"  [FAIL] Response is not valid JSON: {e}")
        return False

    # Validate structure
    passed = True

    if "image_b64_out" not in data:
        print("  [FAIL] Missing 'image_b64_out' in response")
        passed = False
    else:
        # Save annotated image
        output_path = os.path.join(OUTPUT_DIR, f"annotated_{filename}")
        if output_path.endswith(".jpg"):
            pass  # keep as-is
        else:
            output_path += ".jpg"
        save_b64_image(data["image_b64_out"], output_path)
        print(f"  [PASS] 'image_b64_out' present ({len(data['image_b64_out'])} chars)")

    if "report" not in data:
        print("  [FAIL] Missing 'report' in response")
        passed = False
    else:
        report = data["report"]
        print(f"  [INFO] Report keys: {list(report.keys())}")

        # Check summary
        if "summary" in report:
            print(f"  [PASS] Summary: {report['summary'][:100]}...")
        else:
            print("  [FAIL] Missing 'summary' in report")
            passed = False

        # Check boxes
        if "boxes" in report:
            print(f"  [PASS] Found {len(report['boxes'])} boxes")
            for box in report["boxes"][:5]:  # Show first 5
                print(f"    - {box.get('id','?')}: {box.get('label','?')} "
                      f"({box.get('severity','?')}) "
                      f"bbox={box.get('bbox_xyxy','?')}")
        else:
            print("  [WARN] Missing 'boxes' in report (may be valid if no defects)")

        # Check recommended actions
        if "recommended_actions" in report:
            print(f"  [PASS] {len(report['recommended_actions'])} recommended actions")
            for action in report["recommended_actions"][:3]:
                print(f"    - {action[:80]}...")
        else:
            print("  [WARN] Missing 'recommended_actions'")

        # Check distress checklist
        if "distress_checklist" in report:
            print(f"  [PASS] Distress checklist present with {len(report['distress_checklist'])} labels")
        else:
            print("  [WARN] Missing 'distress_checklist'")

        # Check report markdown
        if "report_markdown" in report and report["report_markdown"]:
            md_len = len(report["report_markdown"])
            print(f"  [PASS] Report markdown present ({md_len} chars)")
            # Save markdown report
            md_path = os.path.join(OUTPUT_DIR, f"report_{os.path.splitext(filename)[0]}.md")
            with open(md_path, "w") as f:
                f.write(report["report_markdown"])
            print(f"  [SAVED] {md_path}")
        else:
            print("  [WARN] Missing or empty 'report_markdown'")

        # Save full JSON report
        json_path = os.path.join(OUTPUT_DIR, f"report_{os.path.splitext(filename)[0]}.json")
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"  [SAVED] {json_path}")

    return passed


def test_health():
    """Test the health endpoint."""
    print("\n" + "=" * 60)
    print("TEST: Health check")
    print("=" * 60)
    try:
        resp = requests.get(f"{API_URL}/health", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            print(f"  [PASS] Health OK: {data}")
            return True
        else:
            print(f"  [FAIL] Health check returned: {resp.status_code}")
            return False
    except Exception as e:
        print(f"  [ERROR] Health check failed: {e}")
        return False


def main():
    print("=" * 60)
    print("Road Inspection VLM API - End-to-End Test")
    print("=" * 60)
    print(f"API URL: {API_URL}")
    print(f"Test images: {TEST_IMAGE_DIR}")
    print(f"Output dir: {OUTPUT_DIR}")

    results = []

    # Health check
    results.append(("health", test_health()))

    # Auth tests
    results.append(("no_api_key", test_no_api_key()))
    results.append(("wrong_api_key", test_wrong_api_key()))

    # Pick test images
    image_files = sorted(glob.glob(os.path.join(TEST_IMAGE_DIR, "*.jpg")))
    if not image_files:
        print(f"\n[ERROR] No .jpg files found in {TEST_IMAGE_DIR}")
        sys.exit(1)

    print(f"\n[INFO] Found {len(image_files)} images, testing {NUM_TEST_IMAGES}")

    # Pick evenly spaced images for variety
    step = max(1, len(image_files) // NUM_TEST_IMAGES)
    selected = [image_files[i * step] for i in range(min(NUM_TEST_IMAGES, len(image_files)))]

    for i, img_path in enumerate(selected, 1):
        results.append((os.path.basename(img_path), test_analyze_image(img_path, i)))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            all_passed = False

    if all_passed:
        print("\n[SUCCESS] All tests passed!")
    else:
        print("\n[WARNING] Some tests failed. Check output above.")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
