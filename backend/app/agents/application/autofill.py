"""Visible-browser autofill (run on YOUR laptop): fills everything it can answer honestly,
then YOU complete the remaining questions and click submit.

    pip install -r requirements-autofill.txt && playwright install chromium
    python -m app.cli autofill <application_id>
"""
import tempfile
from pathlib import Path

from app.agents.application.auto_apply import _apply_url, _interactive_captcha, app_svc_profile
from app.agents.application.forms import answers_for, fill_page
from app.agents.application.resume import render_pdf
from app.models import Application


def run_autofill(app: Application) -> list[str]:
    from playwright.sync_api import sync_playwright

    if app.status not in ("approved", "prepared"):
        raise RuntimeError(f"Application is already {app.status}")
    docs = {d.kind: d.content for d in app.documents}
    pdf = Path(tempfile.mkdtemp()) / "resume.pdf"
    pdf.write_bytes(render_pdf(docs.get("resume", "")))
    profile = app_svc_profile(app)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(_apply_url(app.job), wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        filled, missing = fill_page(page, answers_for(app.job, docs.get("cover_letter", ""),
                                                      profile.skills if profile else []), str(pdf))
        print(f"Filled {len(filled)} fields.")
        if missing:
            print("Please answer these yourself:\n  - " + "\n  - ".join(missing))
        if _interactive_captcha(page):
            print("This form has a CAPTCHA: complete it yourself.")
        print("Review everything, click SUBMIT yourself, then close the browser window.")
        page.wait_for_event("close", timeout=0)
        browser.close()
    return filled
