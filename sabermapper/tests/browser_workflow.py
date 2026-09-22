"""Run explicitly: .venv/Scripts/python tests/browser_workflow.py.

Uses an isolated local workspace and actual audio/ZIPs. Requires Playwright Chromium.
"""
from pathlib import Path
import json
import tempfile
import threading
from zipfile import ZipFile

from playwright.sync_api import sync_playwright, expect
from sabermapper.server import make_server


def main():
    artifacts = Path("artifacts")
    artifacts.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sabermapper-browser-") as directory:
        server = make_server(directory, port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with sync_playwright() as runtime:
                browser = runtime.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1512, "height": 1100}, device_scale_factor=1)
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{server.server_port}")
                expect(page.get_by_role("heading", name="Make every beat worth playing.")).to_be_visible()
                page.get_by_role("button", name="Explore the demo").click()
                expect(page.get_by_role("heading", name="Neon Circuit", exact=True)).to_be_visible(timeout=30000)
                expect(page.locator("#timeline rect")).not_to_have_count(0)
                page.get_by_role("button", name="Play audio", exact=True).click()
                expect(page.get_by_role("button", name="Pause audio", exact=True)).to_be_visible()
                expect(page.locator("#play-time")).not_to_have_text("0:00 / 0:48", timeout=10000)
                page.get_by_role("button", name="Pause audio", exact=True).click()
                page.locator("#range-start").fill("4")
                page.locator("#range-end").fill("12")
                page.locator("#range-end").press("Tab")
                page.locator("#feedback-text").fill("Keep the rhythm; add more space before the next phrase.")
                page.get_by_role("button", name="Save feedback", exact=True).click()
                expect(page.locator("#feedback-list")).to_contain_text("Keep the rhythm")
                page.locator(".section-card").first.click()
                section = json.loads(page.locator("#section-editor").input_value())
                section["intent"] = "Reviewed opening; preserve the pulse"
                page.locator("#section-editor").fill(json.dumps(section))
                page.get_by_role("button", name="Save section", exact=True).click()
                expect(page.locator("#sections")).to_contain_text("Reviewed opening")
                page.locator(".section-card").first.click()
                page.get_by_role("button", name="Lock section", exact=True).click()
                expect(page.locator("#section-dialog")).not_to_be_visible()
                page.locator(".section-card").first.click()
                expect(page.get_by_role("button", name="Save section", exact=True)).to_be_disabled()
                page.get_by_role("button", name="Unlock section", exact=True).click()
                expect(page.locator("#section-dialog")).not_to_be_visible()
                with page.expect_download() as download:
                    page.get_by_role("button", name="Export map", exact=False).click()
                path = Path(directory) / "demo.zip"
                download.value.save_as(path)
                with ZipFile(path) as archive:
                    assert {"Info.dat", "Expert.dat", "song.ogg", "cover.png"} <= set(archive.namelist())
                    assert len(json.loads(archive.read("Expert.dat"))["colorNotes"]) > 40
                page.screenshot(path=str(artifacts / "studio-desktop.png"), full_page=True)
                page.get_by_role("button", name="Pattern library", exact=False).click()
                expect(page.locator("#busy")).not_to_be_visible()
                page.locator("#archive-file").set_input_files(path)
                expect(page.locator("#corpus-rows")).to_contain_text("ready", timeout=15000)
                page.get_by_role("button", name="Extract patterns", exact=True).click()
                expect(page.locator("#pattern-results .pattern-card").first).to_be_visible(timeout=15000)
                page.get_by_role("button", name="Find phrases", exact=True).click()
                expect(page.locator("#busy")).not_to_be_visible()
                expect(page.locator("#pattern-results")).to_contain_text("No compatible phrases")
                page.screenshot(path=str(artifacts / "library-desktop.png"), full_page=True)
                page.get_by_role("button", name="Research & evaluation", exact=False).click()
                expect(page.get_by_role("heading", name="Research notebook")).to_be_visible()
                page.get_by_role("button", name="Studio", exact=False).click()
                page.set_viewport_size({"width": 390, "height": 844})
                expect(page.get_by_role("heading", name="Neon Circuit", exact=True)).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "mobile page overflows horizontally"
                page.screenshot(path=str(artifacts / "studio-mobile.png"), full_page=True)
                assert not errors, errors
                browser.close()
                print(json.dumps({"browser": "Chromium", "result": "passed", "page_errors": errors,
                                  "coverage": ["demo creation", "audio playback", "range feedback", "section edit", "lock/unlock", "ZIP download", "map import", "pattern extraction", "same-song retrieval exclusion", "research", "mobile layout"]}))
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
