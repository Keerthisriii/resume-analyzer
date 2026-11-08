from extract import extract_text
from llm import ask_llm

# 1. Read the resume
resume = extract_text("sample_resume.pdf")

# 2. The job you are applying for (replace with a real job description)
job_description = """Design, develop, and deploy scalable and secure cloud-based applications on AWS.

Collaborate with cross-functional teams to identify and prioritize project requirements.

Develop and maintain high-quality code using best practices and coding standards.

Troubleshoot and resolve technical issues efficiently.

Participate in code reviews and contribute to improving overall code quality.

Stay updated with the latest trends and technologies in cloud computing

"""

# 3. Build the prompt
prompt = f"""You are an expert recruiter and ATS (Applicant Tracking System) specialist.
Analyze the resume below against the job description.

Return your answer in exactly this format:
"Step 1: List the 8 to 12 most important skills, tools, or competencies in the "
        "job description. Each must be SHORT (1 to 4 words), like 'AWS', 'Java', "
        "'CI/CD', 'code reviews', 'troubleshooting'. Do not copy full sentences.\n"
"Step 2: For each one, decide if the resume shows it. If yes, copy a SHORT "
        "exact quote (max 6 words) from the resume as evidence. If the resume does "
        "not show it, set in_resume to false and evidence to an empty string.\n"
        "Never invent skills or evidence.\n\n"
3. MISSING SKILLS: important skills in the job description that the resume lacks
4. IMPROVEMENTS: three specific, actionable suggestions

Be honest and specific. Do not invent skills that are not in the resume.

RESUME:
{resume}

JOB DESCRIPTION:
{job_description}
"""

# 4. Ask the LLM and show the result
print(ask_llm(prompt))