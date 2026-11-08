 from extract import extract_text
from analyzer import analyze_resume

resume = extract_text("sample_resume.pdf")
job_description = """
Paste a real job description here.
"""

result = analyze_resume(resume, job_description, on_step=print)
print(result["coverage"])
for r in result["requirements"]:
    print(r["status"], "|", r["skill"], "|", r["evidence"])