import json
import re
from functools import lru_cache

from llm import ask_llm

CATEGORIES = ["Technical skill", "Tool/Platform", "Responsibility", "Soft skill", "Education/Certification"]
PRIORITIES = ["Must-have", "Nice-to-have"]
STATUS_POINTS = {"Matched": 1.0, "Partial": 0.5, "Not found": 0.0}
PRIORITY_WEIGHT = {"Must-have": 2, "Nice-to-have": 1}


# ---------- helpers ----------
def normalize(text):
    text = text or ""
    replacements = {"\u2011": "-", "\u2010": "-", "\u2013": "-", "\u2014": "-",
                    "\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'}
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    text = " ".join(text.lower().split())
    return re.sub(r"\s*-\s*", "-", text)


def squash(text):
    """Keep only letters, digits, + and # so quotes match despite PDF spacing."""
    return re.sub(r"[^a-z0-9+#]", "", normalize(text))


def keyword_in_resume(skill, resume_norm):
    s = normalize(skill)
    for v in {s, s.replace("-", " "), s.replace(" ", "-")}:
        if re.search(r"(?<![a-z0-9])" + re.escape(v) + r"(?![a-z0-9])", resume_norm):
            return True
    return False


def ask_json(prompt, tries=3):
    for _ in range(tries):
        raw = ask_llm(prompt)
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            return json.loads(raw[start:end])
        except json.JSONDecodeError:
            continue
    raise ValueError("The model did not return valid JSON after several tries. Please click Analyze again.")


# ---------- Agent 1: requirement extractor ----------
@lru_cache(maxsize=32)
def _extract_cached(job_description):
    prompt = (
        "You are a senior technical recruiter. Read the job description and list its "
        "8 to 14 most important requirements.\n\n"
        "Rules:\n"
        "- Each 'skill' must be SHORT (1 to 4 words), e.g. 'AWS', 'REST APIs', 'code reviews'. No full sentences.\n"
        "- Group closely related items into one (use 'AWS', not 'AWS', 'EC2' and 'RDS' separately).\n"
        "- 'category' must be exactly one of: " + ", ".join(CATEGORIES) + ".\n"
        "- 'priority' is 'Nice-to-have' only if the text says nice to have, preferred, bonus or optional; "
        "otherwise 'Must-have'.\n\n"
        "Reply with ONLY valid JSON in this shape:\n"
        '{"requirements": [{"skill": "...", "category": "...", "priority": "..."}]}\n\n'
        "JOB DESCRIPTION:\n" + job_description + "\n"
    )
    data = ask_json(prompt)
    rows, seen = [], set()
    for item in data.get("requirements", []):
        skill = str(item.get("skill", "")).strip()
        key = normalize(skill)
        if not skill or key in seen:
            continue
        seen.add(key)
        category = item.get("category") if item.get("category") in CATEGORIES else "Technical skill"
        priority = item.get("priority") if item.get("priority") in PRIORITIES else "Must-have"
        rows.append({"skill": skill, "category": category, "priority": priority})
    if not rows:
        raise ValueError("Could not find any requirements in the job description.")
    return rows


def extract_requirements(job_description):
    return [dict(r) for r in _extract_cached(job_description.strip())]


# ---------- Agent 2: evidence matcher ----------
def match_evidence(resume, requirements):
    names = [r["skill"] for r in requirements]
    prompt = (
        "You are an ATS analyst. For each requirement, check the resume.\n\n"
        "Status rules:\n"
        "- 'Matched': the resume clearly shows hands-on use (project, experience or certification).\n"
        "- 'Partial': only mentioned in a list, or related but not the same.\n"
        "- 'Not found': absent.\n"
        "For Matched or Partial, 'evidence' must be an EXACT quote copied from the resume (max 8 words). "
        "For Not found, evidence is an empty string. Never invent evidence.\n\n"
        "Reply with ONLY valid JSON in this shape:\n"
        '{"matches": [{"skill": "...", "status": "Matched", "evidence": "..."}]}\n\n'
        "REQUIREMENTS:\n" + json.dumps(names) + "\n\n"
        "RESUME:\n" + resume + "\n"
    )
    data = ask_json(prompt)
    by_name = {normalize(m.get("skill", "")): m for m in data.get("matches", [])}
    resume_norm = normalize(resume)
    resume_squashed = squash(resume)

    rows = []
    for req in requirements:
        m = by_name.get(normalize(req["skill"]), {})
        claimed = m.get("status", "Not found")
        quote = str(m.get("evidence", "") or "").strip()
        verified = len(squash(quote)) >= 3 and squash(quote) in resume_squashed

        # Python verifies every claim against the real resume text
        if claimed == "Matched" and verified:
            status, evidence = "Matched", quote
        elif claimed in ("Matched", "Partial") and verified:
            status, evidence = "Partial", quote
        elif keyword_in_resume(req["skill"], resume_norm):
            status, evidence = "Partial", "Keyword appears in resume (no detailed evidence)"
        else:
            status, evidence = "Not found", ""
        rows.append({**req, "status": status, "evidence": evidence})
    return rows


# ---------- coverage (pure Python) ----------
def compute_coverage(rows):
    def pct(subset):
        total = sum(PRIORITY_WEIGHT[r["priority"]] for r in subset)
        if not total:
            return None
        got = sum(PRIORITY_WEIGHT[r["priority"]] * STATUS_POINTS[r["status"]] for r in subset)
        return round(100 * got / total)

    by_category = {}
    for cat in sorted({r["category"] for r in rows}):
        by_category[cat] = pct([r for r in rows if r["category"] == cat])
    return {
        "overall": pct(rows),
        "must_have": pct([r for r in rows if r["priority"] == "Must-have"]),
        "nice_to_have": pct([r for r in rows if r["priority"] == "Nice-to-have"]),
        "by_category": by_category,
    }


# ---------- Agent 3: ATS / format auditor (rules only, no LLM) ----------
SECTION_PATTERNS = {
    "Summary / Objective section": r"\b(summary|objective|profile)\b",
    "Education section": r"\beducation\b",
    "Skills section": r"\bskills?\b",
    "Projects section": r"\bprojects?\b",
    "Experience / Internship section": r"\b(experience|internship|work history)\b",
    "Certifications section": r"\bcertifications?\b",
}


def count_metrics(text):
    t = re.sub(r"\+?\d[\d\s-]{8,}\d", " ", text)      # remove phone numbers
    t = re.sub(r"\b(19|20)\d{2}\b", " ", t)           # remove years
    return len(re.findall(r"\d+(?:\.\d+)?\s?%|\b\d+\+|\b\d{2,}\b", t))


def audit_format(resume):
    low = resume.lower()
    words = len(resume.split())
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "result": "Pass" if ok else "Review", "detail": detail})

    add("Email address", bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", resume)), "Recruiters need a visible email.")
    add("Phone number", bool(re.search(r"\+?\d[\d\s-]{8,}\d", resume)), "Include a reachable phone number.")
    add("LinkedIn or GitHub link", bool(re.search(r"linkedin\.com|github\.com", low)),
        "Links let recruiters verify your work.")
    for name, pattern in SECTION_PATTERNS.items():
        add(name, bool(re.search(pattern, low)), "Standard headings help ATS software parse your resume.")
    add("Length", 250 <= words <= 1000, "Found " + str(words) + " words (aim for about 250 to 1000).")
    metrics = count_metrics(resume)
    add("Quantified results", metrics >= 3, "Found " + str(metrics) + " numbers/metrics. Add numbers to show impact.")
    return checks


# ---------- Agent 4: career advisor ----------
def advise(resume, rows):
    gaps = [{"skill": r["skill"], "priority": r["priority"], "status": r["status"]}
            for r in rows if r["status"] != "Matched"]
    matched = [r["skill"] for r in rows if r["status"] == "Matched"]
    prompt = (
        "You are a career coach reviewing a student's resume for a specific job.\n"
        "Matched requirements: " + json.dumps(matched) + "\n"
        "Gaps (Not found or Partial): " + json.dumps(gaps) + "\n\n"
        "Write:\n"
        "- 'summary': 3 sentences, honest and specific.\n"
        "- 'strengths': up to 4 short strengths that are visible in the resume.\n"
        "- 'recommendations': up to 5, most important gaps first (Must-have before Nice-to-have). Each has "
        "'gap', 'action' (what to learn or add, concrete) and 'example_bullet' (a resume bullet TEMPLATE "
        "using [brackets] for details the student must fill in).\n"
        "Never claim the student has done something that is not in the resume.\n\n"
        "Reply with ONLY valid JSON in this shape:\n"
        '{"summary": "...", "strengths": ["..."], "recommendations": '
        '[{"gap": "...", "action": "...", "example_bullet": "..."}]}\n\n'
        "RESUME:\n" + resume + "\n"
    )
    data = ask_json(prompt)
    recs = []
    for r in data.get("recommendations", [])[:6]:
        recs.append({"gap": str(r.get("gap", "")), "action": str(r.get("action", "")),
                     "example_bullet": str(r.get("example_bullet", "") or "")})
    return {
        "summary": str(data.get("summary", "")),
        "strengths": [str(s) for s in data.get("strengths", [])][:5],
        "recommendations": recs,
    }


# ---------- pipeline ----------
def analyze_resume(resume, job_description, on_step=None):
    step = on_step or (lambda message: None)

    step("Agent 1/4: extracting requirements from the job description...")
    requirements = extract_requirements(job_description)

    step("Agent 2/4: matching requirements to resume evidence...")
    rows = match_evidence(resume, requirements)

    step("Agent 3/4: auditing resume format for ATS...")
    checks = audit_format(resume)

    step("Agent 4/4: writing recommendations...")
    advice = advise(resume, rows)

    counts = {
        "total": len(rows),
        "matched": sum(1 for r in rows if r["status"] == "Matched"),
        "partial": sum(1 for r in rows if r["status"] == "Partial"),
        "missing": sum(1 for r in rows if r["status"] == "Not found"),
    }
    return {
        "requirements": rows,
        "coverage": compute_coverage(rows),
        "counts": counts,
        "ats_checks": checks,
        "summary": advice["summary"],
        "strengths": advice["strengths"],
        "recommendations": advice["recommendations"],
    }