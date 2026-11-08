from datetime import date

import pandas as pd
import streamlit as st

from analyzer import analyze_resume
from extract import extract_text

st.set_page_config(page_title="Resume Analyzer", page_icon="📄", layout="wide")

st.markdown(
    """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
.block-container {padding-top: 2rem; max-width: 1200px;}
.hero p {opacity: .75; font-size: 1.05rem;}
div[data-testid="stMetric"] {
    border: 1px solid rgba(128,128,128,.25);
    border-radius: 12px;
    padding: 14px 16px;
    background: rgba(128,128,128,.06);
}
</style>
""",
    unsafe_allow_html=True,
)

STATUS_LABEL = {"Matched": "✅ Matched", "Partial": "🟡 Partial", "Not found": "❌ Not found"}


def fmt_pct(value):
    return "n/a" if value is None else f"{value}%"


def build_report(result, meta):
    cov = result["coverage"]
    lines = [
        "# Resume Analysis Report", "",
        f"- Resume file: {meta['file']}",
        f"- Date: {meta['date']}", "",
        "## Coverage", "",
        f"- Overall: {fmt_pct(cov['overall'])}",
        f"- Must-have requirements: {fmt_pct(cov['must_have'])}",
        f"- Nice-to-have requirements: {fmt_pct(cov['nice_to_have'])}", "",
        "## Executive summary", "", result["summary"], "",
        "## Requirement matrix", "",
        "| Requirement | Category | Priority | Status | Evidence |",
        "|---|---|---|---|---|",
    ]
    for r in result["requirements"]:
        evidence = r["evidence"].replace("|", "/")
        lines.append(f"| {r['skill']} | {r['category']} | {r['priority']} | {r['status']} | {evidence} |")
    lines += ["", "## ATS and format audit", ""]
    for c in result["ats_checks"]:
        lines.append(f"- {c['check']}: {c['result']} ({c['detail']})")
    lines += ["", "## Recommendations", ""]
    for i, rec in enumerate(result["recommendations"], 1):
        lines.append(f"{i}. **{rec['gap']}**: {rec['action']}")
        if rec["example_bullet"]:
            lines.append(f"   - Example bullet (use only if true): {rec['example_bullet']}")
    return "\n".join(lines)


# ---------- sidebar ----------
with st.sidebar:
    st.header("About this tool")
    st.write(
        "A four-stage pipeline reviews a resume against a job description:\n\n"
        "1. **Requirement extractor** (LLM)\n"
        "2. **Evidence matcher** (LLM + Python verification)\n"
        "3. **ATS format auditor** (rules only)\n"
        "4. **Career advisor** (LLM)"
    )
    st.divider()
    st.subheader("How coverage is calculated")
    st.caption(
        "Each requirement is Matched (1 point), Partial (0.5) or Not found (0). "
        "Must-have requirements count double. Coverage = points earned / points possible. "
        "A match needs a quote that Python confirms exists in the resume."
    )
    st.subheader("Limitations")
    st.caption(
        "Results are decision support, not a hiring verdict. The LLM can misjudge context, "
        "scanned PDFs cannot be read, and requirement lists can vary slightly between job descriptions."
    )

# ---------- header and inputs ----------
st.markdown(
    '<div class="hero"><h1>📄 Resume Analyzer</h1>'
    "<p>Evidence-based resume review against a job description, with ATS format checks "
    "and targeted recommendations.</p></div>",
    unsafe_allow_html=True,
)

left, right = st.columns(2)
with left:
    uploaded_file = st.file_uploader("Resume (PDF)", type="pdf")
with right:
    job_description = st.text_area("Job description", height=180, placeholder="Paste the full job description here...")

run = st.button("Analyze resume", type="primary")

if run:
    if uploaded_file is None or not job_description.strip():
        st.warning("Please upload a resume and paste a job description.")
    else:
        resume_text = extract_text(uploaded_file)
        if len(resume_text.split()) < 50:
            st.error("Could not read enough text from this PDF. It may be a scanned image.")
        else:
            try:
                with st.status("Running analysis pipeline...", expanded=True) as status:
                    result = analyze_resume(resume_text, job_description, on_step=st.write)
                    status.update(label="Analysis complete", state="complete", expanded=False)
                st.session_state["result"] = result
                st.session_state["meta"] = {"file": uploaded_file.name, "date": date.today().isoformat()}
            except Exception as e:
                st.error(f"Something went wrong: {e}")

# ---------- results ----------
result = st.session_state.get("result")
meta = st.session_state.get("meta")

if result:
    cov = result["coverage"]
    counts = result["counts"]

    tab_overview, tab_matrix, tab_ats, tab_recs, tab_export = st.tabs(
        ["Overview", "Requirement matrix", "ATS and format audit", "Recommendations", "Export"]
    )

    with tab_overview:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Overall coverage", fmt_pct(cov["overall"]))
        c2.metric("Must-have coverage", fmt_pct(cov["must_have"]))
        c3.metric("Requirements matched", f"{counts['matched']} / {counts['total']}")
        c4.metric("Partial / Not found", f"{counts['partial']} / {counts['missing']}")

        st.subheader("Executive summary")
        st.write(result["summary"])

        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Strengths")
            for s in result["strengths"]:
                st.write("- " + s)
        with col_b:
            st.subheader("Coverage by category")
            chart_df = pd.DataFrame(
                {"Coverage %": [v if v is not None else 0 for v in cov["by_category"].values()]},
                index=list(cov["by_category"].keys()),
            )
            st.bar_chart(chart_df)

    with tab_matrix:
        st.caption("Each status is backed by a quote from the resume that was verified against the extracted text.")
        df = pd.DataFrame(result["requirements"])
        df["Status"] = df["status"].map(STATUS_LABEL)
        show = df.rename(columns={"skill": "Requirement", "category": "Category",
                                  "priority": "Priority", "evidence": "Evidence from resume"})
        show = show[["Requirement", "Category", "Priority", "Status", "Evidence from resume"]]
        options = list(STATUS_LABEL.values())
        chosen = st.multiselect("Filter by status", options, default=options)
        st.dataframe(
            show[show["Status"].isin(chosen)],
            hide_index=True,
            column_config={"Evidence from resume": st.column_config.TextColumn(width="large")},
        )

    with tab_ats:
        checks = result["ats_checks"]
        passed = sum(1 for c in checks if c["result"] == "Pass")
        st.metric("Checks passed", f"{passed} / {len(checks)}")
        ats_df = pd.DataFrame(checks)
        ats_df["result"] = ats_df["result"].map({"Pass": "✅ Pass", "Review": "⚠️ Review"})
        ats_df = ats_df.rename(columns={"check": "Check", "result": "Result", "detail": "Details"})
        st.dataframe(ats_df, hide_index=True)

    with tab_recs:
        if not result["recommendations"]:
            st.success("No major gaps found for this job description.")
        for i, rec in enumerate(result["recommendations"], 1):
            with st.expander(f"{i}. {rec['gap']}", expanded=(i == 1)):
                st.markdown(f"**What to do:** {rec['action']}")
                if rec["example_bullet"]:
                    st.markdown("**Example bullet (use only if it is true for you):**")
                    st.code(rec["example_bullet"], language=None)

    with tab_export:
        st.write("Download the full analysis for your records or report.")
        st.download_button("Download report (Markdown)", build_report(result, meta),
                           file_name="resume_analysis_report.md", mime="text/markdown")
        csv = pd.DataFrame(result["requirements"]).to_csv(index=False)
        st.download_button("Download requirement matrix (CSV)", csv,
                           file_name="requirement_matrix.csv", mime="text/csv")