"""Exercise the actual UI and Pyodide worker; no mocked conversion results.

Start the HTTP server first. See DEVELOPMENT_AR.md for installation and usage.
"""
import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import shutil
import time
import xml.etree.ElementTree as ET

from playwright.async_api import async_playwright, expect


SVG = "{http://www.w3.org/2000/svg}"


async def convert(page, timeout):
    await page.locator("#process").click()
    await expect(page.locator("#cancel")).to_be_visible()
    deadline = time.monotonic() + timeout
    previous = None
    while time.monotonic() < deadline:
        status = await page.locator("#status").inner_text()
        if status != previous:
            print(status, flush=True)
            previous = status
        if await page.locator("#cancel").is_hidden():
            assert await page.locator("#svg").is_enabled(), status
            assert int(await page.locator("#regionCount").inner_text()) > 0
            await expect(page.locator("#selection")).to_have_text("انقر خلية في المعاينة لعرض معلوماتها.")
            await expect(page.locator("#colorError")).not_to_have_text("—")
            return
        await asyncio.sleep(0.5)
    raise AssertionError(f"Conversion timed out: {previous}")


async def download(page, button, output):
    output.mkdir(parents=True, exist_ok=True)
    async with page.expect_download() as event:
        await page.locator(button).click()
    item = await event.value
    assert await item.failure() is None
    target = output / item.suggested_filename
    await item.save_as(target)
    return target


async def make_image(page, mime, tiles=False):
    # Actual image bytes go through the file input and browser image decoder.
    data = await page.evaluate("""({mime, tiles}) => {
        const c = document.createElement('canvas'); c.width=128; c.height=128;
        const x = c.getContext('2d');
        if (tiles) {
            for (let y=0;y<8;y++) for (let i=0;i<8;i++) {
                x.fillStyle=`rgb(${16+i*32},${16+y*32},128)`;
                x.fillRect(i*16,y*16,16,16);
            }
        } else {
            x.fillStyle='#f6e9cd'; x.fillRect(0,0,128,128);
            x.fillStyle='#40816b'; x.fillRect(16,20,96,88);
            x.fillStyle='#d47157'; x.fillRect(40,40,48,48);
        }
        return c.toDataURL(mime).split(',')[1];
    }""", {"mime": mime, "tiles": tiles})
    extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[mime]
    return {"name": f"upload.{extension}", "mimeType": mime,
            "buffer": base64.b64decode(data)}


async def main(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    errors, failed_requests, workers = [], [], []
    summary = {}
    async with async_playwright() as p:
        launch = {"headless": True}
        executable = args.chromium or shutil.which("chromium")
        if executable:
            launch["executable_path"] = executable
        # Reuse the managed proxy and normal browser TLS verification.
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if proxy:
            launch["proxy"] = {"server": proxy, "bypass": "localhost,127.0.0.1"}
        browser = await p.chromium.launch(**launch)
        context = await browser.new_context(viewport={"width": 1440, "height": 1100})
        page = await context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("requestfailed", lambda request: failed_requests.append(
            {"url": request.url, "failure": request.failure}))
        page.on("worker", lambda worker: workers.append(worker.url))
        try:
            response = await page.goto(args.url)
            assert response.status == 200
            await expect(page.locator("html")).to_have_attribute("dir", "rtl")
            await expect(page.locator("#process")).to_be_disabled()
            for file in ["style.css", "app.js", "worker.js", "engine.js",
                         "v5-core.py", "pipeline.py", "reference.svg"]:
                response = await context.request.get(args.url.rstrip("/") + "/" + file)
                assert response.status == 200, file
            await page.locator("#reference").click()
            await expect(page.locator("#referenceDialog")).to_be_visible()
            await page.wait_for_function("document.querySelector('#referenceDialog img').naturalWidth > 0")
            await page.locator("#closeReference").click()
            summary["http_assets_reference"] = "passed"

            # Invalid uploads must produce a useful error and leave the UI usable.
            await page.locator("#file").set_input_files({
                "name": "broken.png", "mimeType": "image/png", "buffer": b"not an image"})
            await expect(page.locator("#status")).to_contain_text("تعذر قراءة الصورة")
            await expect(page.locator("#process")).to_be_disabled()
            summary["invalid_upload"] = "passed"

            # The bundled demo uses the default 680px / A3 / medium settings.
            await page.locator("#demo").click()
            await expect(page.locator("#process")).to_be_enabled()
            await convert(page, args.timeout)
            assert workers, "The real Web Worker did not start"
            report_path = await download(page, "#report", output)
            report = json.loads(report_path.read_text())
            assert report["engine"] == "V5.2-detail-guarded"
            metrics = report["metrics"]
            assert metrics["labeled"] > 0
            assert metrics["labeled"] + metrics["missing"] == metrics["cells"]
            assert len(report["unresolved"]) == metrics["missing"]
            assert metrics["precolored"] == 0
            assert report["clientFidelity"] is not None
            assert report["settings"]["paper"] == [297, 420]
            summary["demo_default_metrics"] = metrics
            await page.screenshot(path=str(output / "demo-desktop.png"), full_page=True)

            for view in ["solution", "compare", "overlay", "audit", "outline"]:
                await page.locator(f'[data-view="{view}"]').click()
                assert await page.locator("#art svg").count() > 0
                if view == "overlay":
                    await page.locator("#compareBlend").fill("30")
                    await expect(page.locator("#overlaySolution")).to_have_css("opacity", "0.3")
            await page.locator("#zoom").select_option("2")
            await expect(page.locator("#art")).to_have_css("width", "1200px")
            await page.locator("#zoom").select_option("fit")
            await page.locator("#lineWidth").fill("0.15")
            await page.locator("#lineTone").select_option("#8f9693")
            svg_path = await download(page, "#svg", output)
            svg = ET.parse(svg_path).getroot()
            assert svg.attrib["width"] == "297mm"
            assert svg.attrib["height"] == "420mm"
            assert len(svg.findall(f".//{SVG}text")) >= metrics["labeled"]
            assert svg.find(f".//{SVG}g/{SVG}path").attrib["stroke"] == "#8f9693"
            summary["views_svg_report"] = "passed"

            # Real popup and PDF rendering use the application's print document.
            async with page.expect_popup() as popup_event:
                await page.locator("#print").click()
            popup = await popup_event.value
            await expect(popup.locator("svg")).to_be_visible()
            assert await popup.locator("svg").get_attribute("width") == "297mm"
            pdf = await popup.pdf(path=str(output / "demo-a3.pdf"), prefer_css_page_size=True)
            assert pdf.startswith(b"%PDF-") and len(pdf) > 1000
            await popup.close()
            summary["print_pdf"] = "passed"

            # Upload and process all three supported formats, in the same worker.
            for mime in ["image/png", "image/jpeg", "image/webp"]:
                tiles = mime == "image/webp"
                image = await make_image(page, mime, tiles=tiles)
                await page.locator("#file").set_input_files(image)
                await expect(page.locator("#status")).to_contain_text("الصورة جاهزة")
                await expect(page.locator("#art > img")).to_be_visible()
                await expect(page.locator("#svg")).to_be_disabled()
                await page.locator("#paper").select_option("A4")
                await page.locator("#orientation").select_option("landscape")
                await page.locator("#density").select_option("0")
                await page.locator("#colors").select_option("64" if tiles else "8")
                await convert(page, args.timeout)
                color_count = int(await page.locator("#colorCount").inner_text())
                if tiles or mime == "image/png":
                    assert color_count == (64 if tiles else 3)
                else:
                    assert 3 <= color_count <= 8  # JPEG introduces edge colors.
                if tiles:
                    codes = await page.locator("#art svg g text").all_text_contents()
                    assert "64" in codes and "1" in codes
                # Select a real rendered cell using the public click handler.
                cell = page.locator("#art path[data-id]").first
                geometry = await page.locator("#art path[data-id]").evaluate_all(
                    "nodes => nodes.map(n => n.getAttribute('d'))")
                await cell.dispatch_event("click")
                await expect(page.locator("#recode")).to_be_enabled()
                old_color = await page.locator("#recodeColor").input_value()
                next_color = str((int(old_color) + 1) % int(await page.locator("#colorCount").inner_text()))
                # Codes are 1-based labels with 0-based values. Playwright 1.62
                # matches a value string against labels too, so use the index.
                await page.locator("#recodeColor").select_option(index=int(next_color))
                assert await page.locator("#recodeColor").input_value() == next_color
                await page.locator("#recode").click()
                await expect(page.locator("#cancel")).to_be_hidden(timeout=args.timeout * 1000)
                await expect(page.locator("#svg")).to_be_enabled()
                await expect(page.locator("#selection")).to_have_text("انقر خلية في المعاينة لعرض معلوماتها.")
                assert geometry == await page.locator("#art path[data-id]").evaluate_all(
                    "nodes => nodes.map(n => n.getAttribute('d'))"), "Recode changed cell geometry"
                await page.locator("#art path[data-id]").first.dispatch_event("click")
                assert await page.locator("#recodeColor").input_value() == next_color
                path = await download(page, "#svg", output / mime.replace("/", "-"))
                root = ET.parse(path).getroot()
                assert (root.attrib["width"], root.attrib["height"]) == ("297mm", "210mm")
                summary[mime + "_upload_conversion_recode"] = "passed"

            # A changed setting must invalidate exports until a fresh conversion.
            await page.locator("#font").fill("4.5")
            await expect(page.locator("#svg")).to_be_disabled()
            await expect(page.locator("#status")).to_contain_text("تغيّرت الخيارات")
            await page.locator("#process").click()
            await expect(page.locator("#cancel")).to_be_visible()
            await page.locator("#cancel").click()
            await expect(page.locator("#cancel")).to_be_hidden()
            await expect(page.locator("#process")).to_be_enabled()
            await expect(page.locator("#svg")).to_be_disabled()
            await convert(page, args.timeout)
            summary["settings_cancel_retry"] = "passed"

            await page.set_viewport_size({"width": 390, "height": 844})
            await expect(page.locator("#process")).to_be_visible()
            await expect(page.locator(".metrics")).to_have_css("display", "grid")
            boxes = await page.locator(".metrics > div").evaluate_all("""nodes => nodes.map(n => {
                const r=n.getBoundingClientRect(); return {x:r.x,y:r.y,right:r.right,bottom:r.bottom};
            })""")
            for i, a in enumerate(boxes):
                for b in boxes[i+1:]:
                    assert (a["right"] <= b["x"] + 1 or b["right"] <= a["x"] + 1
                            or a["bottom"] <= b["y"] + 1 or b["bottom"] <= a["y"] + 1), "Metrics overlap"
            await page.screenshot(path=str(output / "mobile.png"), full_page=True)
            summary["mobile_render"] = "passed"
            assert not errors, errors
            assert not failed_requests, failed_requests
            summary["page_errors"] = errors
            summary["failed_requests"] = failed_requests
            summary["status"] = "passed"
        finally:
            await page.screenshot(path=str(output / "last-state.png"), full_page=True)
            (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
            await browser.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765/")
    parser.add_argument("--chromium", help="Path to an installed Chromium executable")
    parser.add_argument("--timeout", type=int, default=300, help="Seconds per conversion")
    parser.add_argument("--output", type=Path, default=Path("test-results"))
    asyncio.run(main(parser.parse_args()))
