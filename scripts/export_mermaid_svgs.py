"""Mermaid .mmd 소스에서 SVG를 생성한다.

순서도 문법을 바꾼 뒤에는 다음을 실행하세요.

    python scripts/export_mermaid_svgs.py
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
DIAGRAMS = ROOT / "views" / "diagrams"

HTML = """
<div id="root" style="width:900px"></div>
<script>
const diagram = {diagram!r};
const root = document.getElementById("root");
const el = document.createElement("div");
el.className = "mermaid";
el.textContent = diagram;
root.appendChild(el);
</script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11.15.0/dist/mermaid.min.js"></script>
<script>
mermaid.initialize({{startOnLoad:false,securityLevel:"loose",htmlLabels:true}});
mermaid.run({{nodes:[document.querySelector(".mermaid")]}});
</script>
"""


async def export_one(mmd_path: Path) -> None:
    diagram = mmd_path.read_text(encoding="utf-8").strip()
    svg_path = mmd_path.with_suffix(".svg")
    html = HTML.format(diagram=diagram)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 960, "height": 1200})
        await page.set_content(html, wait_until="networkidle")
        await page.wait_for_timeout(3000)
        if "Syntax error" in await page.locator("body").inner_text():
            raise RuntimeError(f"{mmd_path.name}: mermaid syntax error")
        outer = await page.locator(".mermaid svg").first.evaluate("el => el.outerHTML")
        svg_path.write_text(outer, encoding="utf-8")
        await browser.close()
    print("wrote", svg_path)


async def main() -> None:
    for mmd_path in sorted(DIAGRAMS.glob("*.mmd")):
        await export_one(mmd_path)


if __name__ == "__main__":
    asyncio.run(main())
