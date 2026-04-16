import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ================= CONFIG =================

SHEET_ID = "1An8HEEx-pDJso87QkZSlE5Ot3yW9sl-59k7XQwQ7iic"
SAVE_TAB = "HED_SUBMISSIONS"

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets.readonly'
]

# ================= PAGE CONFIG =================

st.set_page_config(
    page_title="Application Review",
    page_icon="📋",
    layout="wide"
)

# ================= CUSTOM CSS =================

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Sora:wght@300;400;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

    html, body, [class*="css"] {
        font-family: 'Sora', sans-serif;
    }

    .main {
        background-color: #0f1117;
        color: #e8e8e8;
    }

    .stApp {
        background: linear-gradient(135deg, #0f1117 0%, #1a1f2e 100%);
    }

    h1, h2, h3 {
        font-family: 'Sora', sans-serif;
        font-weight: 700;
    }

    .header-title {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(90deg, #60a5fa, #a78bfa);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }

    .header-sub {
        color: #64748b;
        font-size: 0.95rem;
        margin-bottom: 2rem;
    }

    .card {
        background: #1e2333;
        border: 1px solid #2d3452;
        border-radius: 12px;
        padding: 1.4rem 1.6rem;
        margin-bottom: 1.2rem;
    }

    .card-title {
        font-size: 1rem;
        font-weight: 600;
        color: #a78bfa;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 1rem;
        border-bottom: 1px solid #2d3452;
        padding-bottom: 0.6rem;
    }

    .info-row {
        display: flex;
        gap: 0.5rem;
        margin-bottom: 0.5rem;
        align-items: flex-start;
    }

    .info-label {
        color: #64748b;
        font-size: 0.82rem;
        min-width: 160px;
        padding-top: 2px;
    }

    .info-value {
        color: #e2e8f0;
        font-size: 0.88rem;
        font-weight: 500;
    }

    .badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
    }

    .badge-complete { background: #064e3b; color: #34d399; }
    .badge-partial  { background: #451a03; color: #fb923c; }
    .badge-empty    { background: #1e293b; color: #64748b; }

    .doc-link {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: #1e3a5f;
        color: #60a5fa !important;
        padding: 4px 12px;
        border-radius: 6px;
        font-size: 0.8rem;
        text-decoration: none !important;
        margin: 3px 3px 3px 0;
        border: 1px solid #2563eb44;
    }

    .doc-link:hover {
        background: #1d4ed8;
        color: white !important;
    }

    .sem-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
        gap: 0.8rem;
    }

    .sem-card {
        background: #151929;
        border: 1px solid #2d3452;
        border-radius: 8px;
        padding: 1rem;
    }

    .sem-title {
        color: #7c3aed;
        font-weight: 600;
        font-size: 0.85rem;
        margin-bottom: 0.5rem;
    }

    .app-id-box {
        background: #1e2333;
        border: 1px solid #2d3452;
        border-radius: 12px;
        padding: 2rem;
        max-width: 500px;
        margin: 3rem auto;
        text-align: center;
    }

    .stTextInput input {
        background: #151929 !important;
        border: 1px solid #2d3452 !important;
        color: #e2e8f0 !important;
        border-radius: 8px !important;
    }

    .stButton button {
        background: linear-gradient(135deg, #3b82f6, #7c3aed) !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        padding: 0.5rem 2rem !important;
    }

    .divider {
        border: none;
        border-top: 1px solid #2d3452;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)

# ================= GOOGLE SHEETS =================

@st.cache_resource
def get_sheet_service():
    credentials = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES
    )
    return build('sheets', 'v4', credentials=credentials)

def fetch_by_app_id(app_id):
    service = get_sheet_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"{SAVE_TAB}!A:BZ"
    ).execute()

    values = result.get("values", [])
    if not values:
        return None

    headers = values[0]

    for row in values[1:]:
        if row and row[0].strip() == app_id.strip():
            # Pad row to match header length
            while len(row) < len(headers):
                row.append("")
            return dict(zip(headers, row))

    return None

# ================= HELPER FUNCTIONS =================

def safe_get(d, key):
    val = d.get(key, "")
    return val if val not in ["", "Select", "Select State", "Select Year", "Select Country", None] else "—"

def doc_link_html(url, label):
    if url and url.startswith("http"):
        return f'<a class="doc-link" href="{url}" target="_blank">📄 {label}</a>'
    return f'<span style="color:#475569;font-size:0.8rem;">No document</span>'

def info_row(label, value):
    return f"""
    <div class="info-row">
        <span class="info-label">{label}</span>
        <span class="info-value">{value}</span>
    </div>
    """

def status_badge(status):
    if status == "COMPLETE":
        return '<span class="badge badge-complete">✓ Complete</span>'
    elif status == "PARTIAL":
        return '<span class="badge badge-partial">⚠ Partial</span>'
    else:
        return '<span class="badge badge-empty">○ Empty</span>'

# ================= HEADER =================

st.markdown('<div class="header-title">📋 Application Review Portal</div>', unsafe_allow_html=True)
st.markdown('<div class="header-sub">Enter Application ID to view complete submission details</div>', unsafe_allow_html=True)

# ================= SEARCH =================

col_input, col_btn = st.columns([3, 1])

with col_input:
    app_id = st.text_input("", placeholder="Enter Application ID (e.g. APP001)", label_visibility="collapsed")

with col_btn:
    search = st.button("🔍 Search", use_container_width=True)

if not app_id:
    st.markdown("""
    <div style="text-align:center; margin-top:4rem; color:#334155;">
        <div style="font-size:3rem;">🔍</div>
        <div style="font-size:1.1rem; margin-top:0.5rem;">Enter an Application ID above to begin</div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ================= FETCH DATA =================

with st.spinner("Fetching application data..."):
    data = fetch_by_app_id(app_id)

if data is None:
    st.error(f"❌ No application found for ID: **{app_id}**")
    st.stop()

# ================= DISPLAY =================

form_status = safe_get(data, "form_status") if "form_status" in data else safe_get(data, "Form Status")

col1, col2 = st.columns([2, 1])
with col1:
    st.markdown(f"### Application: `{safe_get(data, 'Application_ID')}`")
with col2:
    badge = status_badge(form_status)
    st.markdown(f"<div style='text-align:right;padding-top:8px'>{badge} &nbsp; Submitted: {safe_get(data, 'Submitted At') or safe_get(data, 'submitted_at')}</div>", unsafe_allow_html=True)

st.markdown("---")

# -------- BASIC INFO --------
st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown('<div class="card-title">🧾 Basic Information</div>', unsafe_allow_html=True)

col_a, col_b = st.columns(2)
with col_a:
    st.markdown(info_row("Application ID", safe_get(data, "Application_ID")), unsafe_allow_html=True)
    st.markdown(info_row("Name", safe_get(data, "Name")), unsafe_allow_html=True)
    st.markdown(info_row("Mobile", safe_get(data, "Mobile")), unsafe_allow_html=True)
    st.markdown(info_row("Email", safe_get(data, "Email")), unsafe_allow_html=True)
with col_b:
    st.markdown(info_row("Loan Amount", safe_get(data, "LoanAmount")), unsafe_allow_html=True)
    st.markdown(info_row("Course Name", safe_get(data, "CourseName")), unsafe_allow_html=True)
    st.markdown(info_row("Loan Status", safe_get(data, "CurrentLoanStatus")), unsafe_allow_html=True)
    folder = data.get("Folder Link", "")
    if folder:
        st.markdown(info_row("Drive Folder", f'<a href="{folder}" target="_blank" style="color:#60a5fa">📁 Open Folder</a>'), unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)

# -------- EDUCATION --------
st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown('<div class="card-title">🎓 Education Details</div>', unsafe_allow_html=True)

edu_col1, edu_col2, edu_col3 = st.columns(3)

with edu_col1:
    st.markdown("**10th Standard**")
    st.markdown(info_row("School", safe_get(data, "school_10")), unsafe_allow_html=True)
    st.markdown(info_row("Board", safe_get(data, "board_10")), unsafe_allow_html=True)
    st.markdown(info_row("State", safe_get(data, "state_10")), unsafe_allow_html=True)
    st.markdown(info_row("Year", safe_get(data, "year_10")), unsafe_allow_html=True)
    st.markdown(info_row("Marks Type", safe_get(data, "marks_type_10")), unsafe_allow_html=True)
    st.markdown(info_row("Marks", safe_get(data, "marks_10")), unsafe_allow_html=True)
    st.markdown(doc_link_html(data.get("doc_10", ""), "10th Marksheet"), unsafe_allow_html=True)

with edu_col2:
    st.markdown("**12th Standard**")
    st.markdown(info_row("School", safe_get(data, "school_12")), unsafe_allow_html=True)
    st.markdown(info_row("Board", safe_get(data, "board_12")), unsafe_allow_html=True)
    st.markdown(info_row("State", safe_get(data, "state_12")), unsafe_allow_html=True)
    st.markdown(info_row("Year", safe_get(data, "year_12")), unsafe_allow_html=True)
    st.markdown(info_row("Marks Type", safe_get(data, "marks_type_12")), unsafe_allow_html=True)
    st.markdown(info_row("Marks", safe_get(data, "marks_12")), unsafe_allow_html=True)
    st.markdown(doc_link_html(data.get("doc_12", ""), "12th Marksheet"), unsafe_allow_html=True)

with edu_col3:
    st.markdown("**Graduation**")
    st.markdown(info_row("College", safe_get(data, "college_grad")), unsafe_allow_html=True)
    st.markdown(info_row("University", safe_get(data, "university_grad")), unsafe_allow_html=True)
    st.markdown(info_row("State", safe_get(data, "state_grad")), unsafe_allow_html=True)
    st.markdown(info_row("Year", safe_get(data, "year_grad")), unsafe_allow_html=True)
    st.markdown(info_row("Marks Type", safe_get(data, "marks_type_grad")), unsafe_allow_html=True)
    st.markdown(info_row("Marks/CGPA", safe_get(data, "marks_grad")), unsafe_allow_html=True)
    st.markdown(doc_link_html(data.get("doc_grad", ""), "Graduation Marksheet"), unsafe_allow_html=True)

st.markdown('<hr class="divider">', unsafe_allow_html=True)
st.markdown("**Competitive Exam**")
exam_col1, exam_col2 = st.columns(2)
with exam_col1:
    st.markdown(info_row("Exam Name", safe_get(data, "exam_name")), unsafe_allow_html=True)
    st.markdown(info_row("Year", safe_get(data, "exam_year")), unsafe_allow_html=True)
with exam_col2:
    st.markdown(info_row("Score", safe_get(data, "exam_score")), unsafe_allow_html=True)
    st.markdown(info_row("Rank", safe_get(data, "exam_rank")), unsafe_allow_html=True)
st.markdown(doc_link_html(data.get("exam_doc", ""), "Exam Scorecard"), unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)

# -------- SEMESTERS --------
st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown('<div class="card-title">📚 Semester Details</div>', unsafe_allow_html=True)

sem_fields = [
    ("College", "sem_college"),
    ("Course", "sem_course"),
    ("Year", "sem_year"),
    ("Marks Type", "sem_marks_type"),
    ("Marks", "sem_marks"),
    ("State", "sem_state"),
]

# Sheet columns for semesters (as saved)
sem_col_groups = []
for i in range(1, 9):
    sem_col_groups.append({
        "no": i,
        "college": f"Sem{i}_College" ,
        "course": f"Sem{i}_Course",
        "year": f"Sem{i}_Year",
        "marks_type": f"Sem{i}_MarksType",
        "marks": f"Sem{i}_Marks",
        "state": f"Sem{i}_State",
        "doc": f"Semester_{i}"
    })

# Try to auto-detect semester columns from the actual headers
all_keys = list(data.keys())

def find_sem_value(data, sem_no, field_keywords):
    """Try multiple possible column name formats"""
    patterns = [
        f"Sem{sem_no}_{field_keywords}",
        f"sem{sem_no}_{field_keywords}",
        f"Semester_{sem_no}_{field_keywords}",
        f"sem_{sem_no}_{field_keywords}",
    ]
    for k in all_keys:
        for p in patterns:
            if k.lower() == p.lower():
                return data.get(k, "")
    return ""

# Build semester display from raw column order
# Columns in sheet: college, course, year, marks_type, marks, state — 6 per semester
# Find starting index of semester data in headers
headers_list = list(data.keys())

# Find index of first semester column — look for pattern
sem_start_idx = None
for idx, h in enumerate(headers_list):
    if any(x in h.lower() for x in ["sem1_college", "semester_1_college", "college (semester"]):
        sem_start_idx = idx
        break

sem_cols_per = 6
semesters_display = []

if sem_start_idx is not None:
    values_list = list(data.values())
    for i in range(8):
        start = sem_start_idx + i * sem_cols_per
        if start + sem_cols_per <= len(values_list):
            sem_vals = values_list[start:start + sem_cols_per]
            doc_key = f"Semester_{i+1}"
            semesters_display.append({
                "no": i + 1,
                "college": sem_vals[0] if len(sem_vals) > 0 else "",
                "course": sem_vals[1] if len(sem_vals) > 1 else "",
                "year": sem_vals[2] if len(sem_vals) > 2 else "",
                "marks_type": sem_vals[3] if len(sem_vals) > 3 else "",
                "marks": sem_vals[4] if len(sem_vals) > 4 else "",
                "state": sem_vals[5] if len(sem_vals) > 5 else "",
                "doc": data.get(doc_key, "")
            })

# Fallback: show raw semester doc links if structure not found
if not semesters_display:
    for i in range(1, 9):
        doc_url = data.get(f"Semester_{i}", "")
        if doc_url:
            semesters_display.append({"no": i, "college": "", "course": "", "year": "", "marks_type": "", "marks": "", "state": "", "doc": doc_url})

if semesters_display:
    cols_sem = st.columns(2)
    for idx, sem in enumerate(semesters_display):
        college = sem.get("college", "").strip()
        marks = sem.get("marks", "").strip()
        doc_url = sem.get("doc", "")
        if not college and not marks and not doc_url:
            continue
        with cols_sem[idx % 2]:
            st.markdown(f'<div class="sem-card">', unsafe_allow_html=True)
            st.markdown(f'<div class="sem-title">Semester {sem["no"]}</div>', unsafe_allow_html=True)
            if college: st.markdown(info_row("College", college), unsafe_allow_html=True)
            if sem.get("course"): st.markdown(info_row("Course", sem["course"]), unsafe_allow_html=True)
            if sem.get("year"): st.markdown(info_row("Year", sem["year"]), unsafe_allow_html=True)
            if sem.get("marks_type"): st.markdown(info_row("Marks Type", sem["marks_type"]), unsafe_allow_html=True)
            if marks: st.markdown(info_row("Marks", marks), unsafe_allow_html=True)
            if sem.get("state"): st.markdown(info_row("State", sem["state"]), unsafe_allow_html=True)
            st.markdown(doc_link_html(doc_url, f"Semester {sem['no']} Marksheet"), unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
else:
    st.markdown('<span style="color:#475569">No semester data found.</span>', unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)

# -------- INTERNSHIP --------
st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown('<div class="card-title">💼 Internship Details</div>', unsafe_allow_html=True)

int_col1, int_col2 = st.columns(2)
with int_col1:
    st.markdown(info_row("Company", safe_get(data, "intern_company")), unsafe_allow_html=True)
    st.markdown(info_row("Role", safe_get(data, "intern_role")), unsafe_allow_html=True)
with int_col2:
    st.markdown(info_row("Duration", safe_get(data, "intern_duration")), unsafe_allow_html=True)
    st.markdown(info_row("State", safe_get(data, "intern_state")), unsafe_allow_html=True)

st.markdown(doc_link_html(data.get("intern_doc", ""), "Internship Certificate"), unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# -------- PLACEMENT --------
st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown('<div class="card-title">🏢 Placement Details</div>', unsafe_allow_html=True)

placed = safe_get(data, "Placed")
st.markdown(info_row("Placed?", placed), unsafe_allow_html=True)

if placed == "Yes":
    pl_col1, pl_col2 = st.columns(2)
    with pl_col1:
        st.markdown(info_row("Company", safe_get(data, "company")), unsafe_allow_html=True)
        st.markdown(info_row("Role", safe_get(data, "role")), unsafe_allow_html=True)
        st.markdown(info_row("CTC", safe_get(data, "ctc")), unsafe_allow_html=True)
    with pl_col2:
        st.markdown(info_row("Country", safe_get(data, "country")), unsafe_allow_html=True)
        st.markdown(info_row("Current Address", safe_get(data, "current_address")), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(doc_link_html(data.get("offer_doc", ""), "Offer Letter"), unsafe_allow_html=True)
    st.markdown(doc_link_html(data.get("address_doc", ""), "Address Proof"), unsafe_allow_html=True)
    st.markdown(doc_link_html(data.get("resume_doc", ""), "Resume"), unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)
