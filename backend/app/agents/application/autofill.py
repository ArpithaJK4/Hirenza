"""Local browser autofill (run on YOUR laptop): fills the form, NEVER clicks submit.

    pip install -r requirements-autofill.txt && playwright install chromium
    python -m app.cli autofill <application_id>
"""
import tempfile
from pathlib import Path

from app.agents.application.resume import render_pdf
from app.agents.application.service import _autofill_values
from app.models import Application

SELECTORS = {
    "greenhouse": {"first_name": "#first_name", "last_name": "#last_name", "email": "#email", "phone": "#phone",
                   "resume": "input[type=file]#resume, input[type=file]"},
    "lever": {"full_name": "input[name=name]", "email": "input[name=email]", "phone": "input[name=phone]",
              "linkedin": "input[name='urls[LinkedIn]']", "github": "input[name='urls[GitHub]']",
              "resume": "input[type=file][name=resume]"},
    "ashby": {"full_name": "input[name='_systemfield_name']", "email": "input[name='_systemfield_email']",
              "phone": "input[type=tel]", "resume": "input[type=file]"},
}
LABEL_HINTS = {"first_name": "first name", "last_name": "last name", "email": "email", "phone": "phone",
               "linkedin": "linkedin", "github": "github", "location": "location"}


def run_autofill(app: Application) -> list[str]:
    from playwright.sync_api import sync_playwright

    if app.status != "approved":
        raise RuntimeError("Approve the application in the review queue first")
    job = app.job
    ats = (job.scope or "").split(":")[0]
    values = _autofill_values()
    values["full_name"] = f"{values['first_name']} {values['last_name']}".strip()
    resume_doc = next((d for d in app.documents if d.kind == "resume"), None)
    pdf = Path(tempfile.mkdtemp()) / "resume.pdf"
    pdf.write_bytes(render_pdf(resume_doc.content if resume_doc else ""))
    filled: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(job.apply_url or job.url, wait_until="domcontentloaded")
        if ats == "lever" and "/apply" not in page.url:
            page.goto(page.url.rstrip("/") + "/apply", wait_until="domcontentloaded")
        for key, sel in SELECTORS.get(ats, {}).items():
            loc = page.locator(sel).first
            try:
                if key == "resume":
                    loc.set_input_files(str(pdf), timeout=3000)
                elif values.get(key):
                    loc.fill(values[key], timeout=3000)
                else:
                    continue
                filled.append(key)
            except Exception:  # noqa: BLE001, S112 - field absent on this form
                continue
        for key, hint in LABEL_HINTS.items():  # generic label-based fallback
            if key in filled or not values.get(key):
                continue
            try:
                page.get_by_label(hint, exact=False).first.fill(values[key], timeout=1500)
                filled.append(key)
            except Exception:  # noqa: BLE001, S112
                continue
        print(f"Filled: {', '.join(filled) or 'nothing'}. Review every field, answer the remaining questions,")
        print("and click SUBMIT yourself. Close the browser window when done.")
        page.wait_for_event("close", timeout=0)
        browser.close()
    return filled
