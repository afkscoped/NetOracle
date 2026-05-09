"""
End-to-end smoke tests for the Three.js 3D digital twin UI.
Uses Playwright for headless browser testing.
"""
import pytest
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8000"

def test_twin_page_loads():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.on("console", lambda msg: print(f"Browser console: {msg.text}"))
            page.on("pageerror", lambda err: print(f"Browser error: {err}"))
            page.goto(f"{BASE_URL}/twin", wait_until="networkidle")
        except Exception as e:
            pytest.skip(f"Could not connect to {BASE_URL}. Ensure uvicorn is running. Error: {e}")
            
        # Canvas element should be present (Three.js renders into it)
        try:
            page.wait_for_selector("canvas", timeout=5000)
        except Exception:
            html = page.evaluate("document.body.innerHTML")
            print(f"BODY HTML: {html}")
            raise
        assert page.locator("canvas").count() > 0, "Three.js canvas not found"
        browser.close()

def test_demo_run_updates_twin():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(f"{BASE_URL}/twin", wait_until="networkidle")
        except Exception as e:
            pytest.skip(f"Could not connect to {BASE_URL}. Ensure uvicorn is running. Error: {e}")
            
        # Trigger demo run
        page.click("button#demo")
        
        # Wait for backend response and UI update (simulates multi-agent diagnosis)
        try:
            page.wait_for_function("""() => {
                const scene = window.__THREE_SCENE__;
                if (!scene) return false;
                
                const node = scene.getObjectByName('upf_1');
                return node && node.userData && node.userData.fault_probability >= 0.45;
            }""", timeout=15000)
            is_alert_state = True
        except Exception:
            is_alert_state = False
        
        assert is_alert_state is True, "upf_1 did not enter alert state after demo injection"
        
        # Wait for camera animation to finish (or auto-rotation to settle)
        page.evaluate("""() => {
            return new Promise((resolve) => {
                if (window.__THREE_CAMERA__) {
                    let lastPos = window.__THREE_CAMERA__.position.clone();
                    let attempts = 0;
                    const checkMovement = setInterval(() => {
                        attempts++;
                        const currentPos = window.__THREE_CAMERA__.position;
                        if (currentPos.distanceTo(lastPos) < 0.01 || attempts > 10) {
                            clearInterval(checkMovement);
                            resolve();
                        }
                        lastPos = currentPos.clone();
                    }, 500);
                } else {
                    resolve();
                }
            });
        }""")
        
        # Capture a screenshot as requested
        import os
        os.makedirs("artifacts", exist_ok=True)
        page.screenshot(path="artifacts/camera_focused_on_alert.png")
        
        # Visual/Text Verification: Ensure audit log has been updated
        timeline_html = page.locator("#timeline").inner_html()
        assert len(timeline_html) > 0, "Timeline empty after demo run"
        
        browser.close()
