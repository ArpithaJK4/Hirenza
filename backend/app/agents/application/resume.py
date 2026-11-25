"""Resume parsing, tailoring (no fabrication) and ATS-friendly PDF rendering."""
import io
import re

from app.agents.matching.skills import extract_skills

SECTION_RX = re.compile(
    r"^\s*(professional summary|summary|profile|technical skills|skills|professional experience|"
    r"work experience|experience|selected projects|projects|education|certifications?)\s*:?\s*$", re.I | re.M)
CANON = {"professional summary": "summary", "profile": "summary", "technical skills": "skills",
         "professional experience": "experience", "work experience": "experience",
         "selected projects": "projects", "certification": "certifications"}
PDF_MAGIC, ZIP_MAGIC = b"%PDF", b"PK\x03\x04"


class ResumeError(ValueError):
    pass


def extract_text(data: bytes, filename: str) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        if not data.startswith(PDF_MAGIC):
            raise ResumeError("File is not a valid PDF")
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    if name.endswith(".docx"):
        if not data.startswith(ZIP_MAGIC):
            raise ResumeError("File is not a valid DOCX")
        import docx
        return "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)
    if name.endswith((".txt", ".md")):
        return data.decode("utf-8", "replace")
    raise ResumeError("Upload a PDF, DOCX, TXT or MD file")


def split_sections(text: str) -> dict[str, str]:
    parts = SECTION_RX.split(text)
    out = {"header": parts[0].strip()}
    for i in range(1, len(parts) - 1, 2):
        key = parts[i].strip().lower()
        out[CANON.get(key, key)] = parts[i + 1].strip()
    return out


def parse_resume(data: bytes, filename: str) -> dict:
    text = extract_text(data, filename)
    if len(text.strip()) < 100:
        raise ResumeError("Could not read text from this file (scanned PDF?). Upload a text-based PDF/DOCX.")
    return {"text": text, "sections": split_sections(text), "skills": extract_skills(text)}


def _bullets(block: str) -> list[str]:
    return [ln.strip(" •-*\t") for ln in block.splitlines() if ln.strip(" •-*\t")]


def _relevance(line: str, jd_skills: set[str]) -> int:
    return len(set(extract_skills(line)) & jd_skills)


def tailor(sections: dict, resume_skills: list[str], jd_skills: list[str], variant: str = "A") -> str:
    """Reorder (never invent) content so JD-relevant facts come first.
    Variant A: skills section first. Variant B: experience first (A/B test)."""
    jd = set(jd_skills)
    matched = [s for s in resume_skills if s in jd]
    rest = [s for s in resume_skills if s not in jd]
    md = [sections.get("header", "").strip(), ""]
    if sections.get("summary"):
        md += ["## Summary", sections["summary"].strip(), ""]
    skills_md = ["## Key Skills", ", ".join(matched + rest), ""]

    exp_md: list[str] = []
    if sections.get("experience"):
        exp_md.append("## Experience")
        for line in sections["experience"].splitlines():
            exp_md.append(line)  # keep structure; bullets re-ranked below
        bullets = _bullets(sections["experience"])
        ranked = sorted(bullets, key=lambda b: -_relevance(b, jd))
        top = [b for b in ranked if _relevance(b, jd)][:6]
        if top:
            exp_md = ["## Most Relevant Experience", *[f"- {b}" for b in top], "", *exp_md]
        exp_md.append("")

    body = (skills_md + exp_md) if variant == "A" else (exp_md + skills_md)
    md += body
    if sections.get("projects"):
        blocks = re.split(r"\n(?=[A-Z][^\n•\-]{3,80}\n)", sections["projects"])
        blocks.sort(key=lambda b: -_relevance(b, jd))
        md += ["## Projects", *blocks, ""]
    for key, title in (("education", "Education"), ("certifications", "Certifications")):
        if sections.get(key):
            md += [f"## {title}", sections[key].strip(), ""]
    return "\n".join(md).strip() + "\n"


def _latin1(s: str) -> str:
    return (s.replace("•", "-").replace("–", "-").replace("—", "-").replace("’", "'").replace("“", '"')
             .replace("”", '"').replace("₹", "Rs ").encode("latin-1", "replace").decode("latin-1"))


def render_pdf(markdown: str) -> bytes:
    """Single-column, plain-font PDF: what ATS parsers read best."""
    from fpdf import FPDF
    pdf = FPDF(format="A4")
    pdf.set_margins(15, 12, 15)
    pdf.set_auto_page_break(True, 12)
    pdf.add_page()
    first = True
    for raw in markdown.splitlines():
        line = _latin1(raw.rstrip())
        if first and line.strip():
            pdf.set_font("Helvetica", "B", 16)
            pdf.multi_cell(0, 8, line.strip(), new_x="LMARGIN", new_y="NEXT")
            first = False
            continue
        if line.startswith("## "):
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 11.5)
            pdf.multi_cell(0, 6, line[3:].upper(), new_x="LMARGIN", new_y="NEXT")
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(1)
        elif line.startswith("- "):
            pdf.set_font("Helvetica", "", 9.5)
            pdf.multi_cell(0, 4.6, "- " + line[2:], new_x="LMARGIN", new_y="NEXT")
        elif line.strip():
            pdf.set_font("Helvetica", "", 9.5)
            pdf.multi_cell(0, 4.6, line, new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.ln(1.5)
    return bytes(pdf.output())
