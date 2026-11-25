"""Generic ATS form engine: collect fields, answer them from your saved answers, report what's missing.
Unknown required questions are NEVER guessed — the application goes to manual review instead."""
import re

from app.agents.matching.skills import canonicalize, extract_skills
from app.core.config import get_settings
from app.guardrails import normalize_company

COLLECT_JS = """
() => {
  const els = Array.from(document.querySelectorAll('input, textarea, select'));
  return els.map((el, i) => {
    const type = (el.getAttribute('type') || el.tagName).toLowerCase();
    let label = '';
    if (el.labels && el.labels.length) label = el.labels[0].innerText;
    if (!label) label = el.getAttribute('aria-label') || el.getAttribute('placeholder') || '';
    if (!label) { const fs = el.closest('fieldset'); if (fs && fs.querySelector('legend')) label = fs.querySelector('legend').innerText; }
    if (!label) { const box = el.closest('.field, .application-question, [class*="field"], [class*="question"]');
                  if (box) label = (box.querySelector('label, .text, legend') || box).innerText.split('\\n')[0]; }
    const visible = !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    const required = el.required || el.getAttribute('aria-required') === 'true' || /\\*\\s*$/.test(label.trim());
    const options = el.tagName === 'SELECT' ? Array.from(el.options).map(o => o.text.trim()).filter(Boolean) : [];
    const optLabel = (type === 'radio' || type === 'checkbox') && el.labels && el.labels.length ? el.labels[0].innerText : '';
    return {i, role: el.getAttribute('role') || '', tag: el.tagName.toLowerCase(), type, name: el.name || el.id || '', label: label.trim().slice(0, 300),
            required, visible, options, optLabel: optLabel.trim(), value: el.value || ''};
  });
}
"""

DECLINE = re.compile(r"decline|prefer not|don.?t wish|do not wish|not to (say|disclose|answer)|i don.?t want", re.I)


def _skill_question(profile_skills: set[str]):
    def f(label: str) -> str | None:
        asked = extract_skills(label)
        if not asked:
            return None  # can't tell what is being asked -> manual
        return "Yes" if all(a in profile_skills for a in asked) else "No"
    return f


def _employed_by(job, past: list[str]):
    def f(label: str) -> str | None:
        co = normalize_company(job.company_name)
        return "Yes" if any(normalize_company(p) == co for p in past) else "No"
    return f


def answers_for(job, cover_letter: str, profile_skills: list[str] | None = None):
    s = get_settings()
    first, _, last = (s.candidate_full_name or "").partition(" ")
    india = (job.country or "") in ("India", "Worldwide", "") or job.remote_type == "remote" and job.country in (None,)
    auth = "Yes" if india else "No"
    sponsor = "No" if india else ("Yes" if (s.candidate_needs_sponsorship_abroad or "").lower().startswith("y") else "No")
    rx = lambda p: re.compile(p, re.I)  # noqa: E731
    return [  # order matters: specific rules first
        (rx(r"(months|years?) of (hands-on |professional )?experience (in|with)|experience (in|with) .*\?"),
         _skill_question(canonicalize(profile_skills or []))),
        (rx(r"first\s*name|given name"), first or None),
        (rx(r"last\s*name|surname|family name"), last or None),
        (rx(r"^(full\s*|legal\s*)?name\b|your name|legal name"), s.candidate_full_name),
        (rx(r"^country\b|country of residence|which country"), "India"),
        (rx(r"e-?mail"), s.candidate_email),
        (rx(r"phone|mobile|contact number"), s.candidate_phone),
        (rx(r"linkedin"), s.candidate_linkedin_url),
        (rx(r"github|portfolio|website|personal (site|url)"), s.candidate_github_url),
        (rx(r"current (company|employer|organi[sz]ation)|^company$|^org"), s.candidate_current_company),
        (rx(r"notice period|when can you (start|join)|earliest start|availability to start"), s.candidate_notice_period),
        (rx(r"expected (ctc|salary|compensation|pay)|salary expectation|desired (salary|compensation)"),
         s.candidate_expected_ctc),
        (rx(r"current (ctc|salary|compensation)"), s.candidate_current_ctc),
        (rx(r"years of (relevant |professional )?experience|how many years"), s.candidate_years_experience),
        (rx(r"relocat|open to work(ing)? from|willing to work from|comfortable (working|commuting)|work from .*office"),
         (s.candidate_willing_to_relocate or "").capitalize() or None),
        (rx(r"sponsor|visa"), sponsor),
        (rx(r"(legally )?(authori[sz]ed|eligible|permitted) to work|right to work|work authori[sz]ation"), auth),
        (rx(r"(current )?location|city|where are you (based|located)"), s.candidate_location),
        (rx(r"how did you (hear|find|learn)|source"), "Company careers page"),
        (rx(r"cover letter|additional information|anything else"), cover_letter),
        (rx(r"(currently|ever|previously) (been )?(employed|worked|contracted)|worked (at|for) .* before|"
            r"former employee"), _employed_by(job, s.candidate_past_employers)),
        (rx(r"degree|highest (level of )?education|qualification"), s.candidate_degree),
        (rx(r"whatsapp|sms|text message|marketing|newsletter"), "No"),
        (rx(r"gender|race|ethnic|veteran|disabilit|pronoun|sexual orientation|hispanic"), "__DECLINE__"),
        (rx(r"privacy|consent|acknowledge|i agree|terms|data processing|gdpr"), "__CHECK__"),
    ]


def answer(label: str, rules) -> str | None:
    for pattern, value in rules:
        if pattern.search(label or ""):
            return value(label) if callable(value) else value
    return None


ACK = re.compile(r"acknowledge|i agree|agree|accept|yes|confirm|i have read", re.I)


def pick_option(options: list[str], value: str) -> str | None:
    if value == "__CHECK__":
        return next((o for o in options if ACK.search(o)), None)
    if value == "__DECLINE__":
        return next((o for o in options if DECLINE.search(o)), None)
    v = value.lower()
    exact = next((o for o in options if o.lower() == v), None)
    return exact or next((o for o in options if o.lower().startswith(v) or v in o.lower()), None)


def _combo(page, el, value: str) -> bool:
    """Custom dropdowns (role=combobox, e.g. new Greenhouse/Ashby forms): open, read options, click the match."""
    ctrl = el.get_attribute("aria-controls") or el.get_attribute("aria-owns")

    def options():  # only the listbox this dropdown controls, and only visible options
        o = page.locator(f"[id='{ctrl}'] [role=option]") if ctrl else page.locator("[role=option]:visible")
        if ctrl and not o.count():
            o = page.locator("[role=option]:visible")
        return o, [o.nth(k).inner_text().strip() for k in range(min(o.count(), 300))]
    el.click(timeout=3000)
    page.wait_for_timeout(350)
    opts, texts = options()
    target = pick_option(texts, value) if texts else None
    if target is None and value not in ("__CHECK__", "__DECLINE__"):
        typed = value.split(",")[0].strip()
        el.fill(typed, timeout=3000)
        page.wait_for_timeout(900)
        opts, texts = options()
        target = pick_option(texts, value) or next((t for t in texts if typed.lower() in t.lower()), None)
    if target:
        opts.nth(texts.index(target)).click(timeout=3000)
        return True
    page.keyboard.press("Escape")
    return False


def fill_page(page, rules, resume_pdf: str) -> tuple[list[str], list[str]]:
    """Fill every recognisable field. Returns (filled_labels, missing_required_labels)."""
    fields = page.evaluate(COLLECT_JS)
    loc = page.locator("input, textarea, select")
    filled, missing = [], []
    radio_groups: dict[str, list[dict]] = {}
    for f in fields:
        if f["type"] in ("hidden", "submit", "button", "image", "reset", "search"):
            continue
        if f["type"] in ("radio", "checkbox") and f["label"] and f["optLabel"] and f["optLabel"] != f["label"]:
            radio_groups.setdefault(f["name"] or f["label"], []).append(f)
            continue
        el = loc.nth(f["i"])
        try:
            if f["type"] == "file":
                if re.search(r"resume|cv", f["label"] + f["name"], re.I) or not filled.count("resume"):
                    el.set_input_files(resume_pdf, timeout=4000)
                    filled.append("resume")
                continue
            if not f["visible"]:
                continue
            val = answer(f["label"] or f["name"], rules)
            if f["type"] == "checkbox":
                if val == "__CHECK__" and f["required"]:
                    el.check(timeout=3000)
                    filled.append(f["label"])
                elif f["required"]:
                    missing.append(f["label"] or f["name"])
                continue
            if f["role"] == "combobox" and val not in (None, ""):
                if _combo(page, el, val):
                    filled.append(f["label"])
                elif f["required"]:
                    missing.append(f["label"])
                continue
            if val in (None, "") or (val == "__CHECK__" and f["tag"] != "select"):
                if f["required"] and not f["value"]:
                    missing.append(f["label"] or f["name"])
                continue
            if f["tag"] == "select":
                opt = pick_option(f["options"], val)
                if opt:
                    el.select_option(label=opt, timeout=3000)
                    filled.append(f["label"])
                elif f["required"]:
                    missing.append(f["label"])
                continue
            if val == "__DECLINE__":
                continue
            el.fill(val, timeout=3000)
            filled.append(f["label"] or f["name"])
        except Exception:  # noqa: BLE001 - one odd field must not crash the run
            if f["required"]:
                missing.append(f["label"] or f["name"])
    for group, opts in radio_groups.items():
        label = opts[0]["label"]
        val = answer(label, rules)
        if val == "__CHECK__" and all(o["type"] == "checkbox" for o in opts):
            for o in opts:
                if o["required"] or len(opts) == 1:
                    loc.nth(o["i"]).check(timeout=3000, force=True)
            filled.append(label)
            continue
        target = pick_option([o["optLabel"] for o in opts], val) if val and val != "__CHECK__" else None
        if target:
            loc.nth(next(o["i"] for o in opts if o["optLabel"] == target)).check(timeout=3000, force=True)
            filled.append(label)
        elif any(o["required"] for o in opts):
            missing.append(label or group)
    return filled, sorted(set(m for m in missing if m))
