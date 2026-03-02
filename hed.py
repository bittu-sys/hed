import streamlit as st
import pandas as pd
import os
import io
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ================= CONFIG =================

FOLDER_ID = "0AKQoF-VACGZsUk9PVA"
SHEET_ID = "1An8HEEx-pDJso87QkZSlE5Ot3yW9sl-59k7XQwQ7iic"
FETCH_TAB = "HED"
SAVE_TAB = "HED_SUBMISSIONS"

SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets'
]

# ================= YEAR OPTIONS =================

year_options = ["Select Year"] + [str(y) for y in range(2000, datetime.now().year + 1)]

credentials = service_account.Credentials.from_service_account_info(
    st.secrets["gcp_service_account"],
    scopes=SCOPES
)

drive_service = build('drive', 'v3', credentials=credentials)
sheet_service = build('sheets', 'v4', credentials=credentials)

# ================= SESSION INIT =================

if "step" not in st.session_state:
    st.session_state.step = 1

if "student_data" not in st.session_state:
    st.session_state.student_data = {}

if "semester_count" not in st.session_state:
    st.session_state.semester_count = 2

# ================= FETCH FUNCTION =================

def fetch_application_data(app_id):

    result = sheet_service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"{FETCH_TAB}!A:G"   # A to G because new columns added
    ).execute()

    values = result.get("values", [])

    for row in values[1:]:
        if row[0] == app_id:
            return {
                "Application_ID": row[0],
                "Name": row[1],
                "Mobile": row[2],
                "Email": row[3],
                "LoanAmount": row[4],
                "CourseName": row[5],
                "CurrentState": row[6]
            }

    return None

def create_student_folder(folder_name):
    file_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [FOLDER_ID]
    }

    folder = drive_service.files().create(
        body=file_metadata,
        fields='id',
        supportsAllDrives=True
    ).execute()

    return folder.get('id')


def upload_file_to_drive(uploaded_file, folder_id, filename):

    file_metadata = {
        'name': filename,
        'parents': [folder_id]
    }

    media = MediaIoBaseUpload(
        uploaded_file,
        mimetype=uploaded_file.type,
        resumable=True
    )

    file = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id',
        supportsAllDrives=True
    ).execute()

    return f"https://drive.google.com/file/d/{file.get('id')}/view"

# ================= SAVE TO SHEET FUNCTION =================

def save_to_sheet(data_dict, folder_link, uploaded_links):

    semester_summary = ""
    for sem in data_dict.get("semester_data", []):
        semester_summary += f"{sem.get('sem_name','')} - {sem.get('marks','')} | "

    values = [[
        data_dict.get("Application_ID",""),
        data_dict.get("Name",""),
        data_dict.get("Mobile",""),
        data_dict.get("Email",""),
        data_dict.get("LoanAmount",""),
        data_dict.get("CourseName",""),
        data_dict.get("CurrentState",""),

        data_dict.get("school_10",""),
        data_dict.get("marks_10",""),
        data_dict.get("school_12",""),
        data_dict.get("marks_12",""),
        data_dict.get("college_grad",""),
        data_dict.get("marks_grad",""),

        data_dict.get("exam_name",""),
        data_dict.get("exam_score",""),

        semester_summary,
        data_dict.get("intern_company",""),
        data_dict.get("Placed",""),

        folder_link,

        uploaded_links.get("doc_10",""),
        uploaded_links.get("doc_12",""),
        uploaded_links.get("doc_grad",""),
        uploaded_links.get("exam_doc",""),
        uploaded_links.get("intern_doc",""),
        uploaded_links.get("offer_doc",""),
        uploaded_links.get("address_doc",""),
        uploaded_links.get("resume_doc",""),

        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ]]

    sheet_service.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range=f"{SAVE_TAB}!A:Z",
        valueInputOption="RAW",
        body={"values": values}
    ).execute()

# ================= HEADER =================

st.title("Domestic Higher Education ")

steps = ["Basic Info","Education","Semester","Internship","Placement","Review"]

# ================= STATUS ENGINE =================

def get_section_status(step):
    d = st.session_state.student_data

    # -------- STEP 1 BASIC --------
    if step == 1:
        required = [d.get("Name"), d.get("Mobile"), d.get("Email")]
        filled = sum([1 for x in required if x])

        if filled == 0:
            return "empty"
        elif filled < len(required):
            return "partial"
        else:
            return "complete"

    # -------- STEP 2 EDUCATION --------
    if step == 2:
        required = [
            d.get("school_10"),
            d.get("marks_10"),
            d.get("school_12"),
            d.get("marks_12"),
            d.get("college_grad"),
            d.get("marks_grad")
        ]
        filled = sum([1 for x in required if x])

        if filled == 0:
            return "empty"
        elif filled < len(required):
            return "partial"
        else:
            return "complete"

    # -------- STEP 3 SEMESTER --------
    if step == 3:
        sem = d.get("semester_data", [])
        if not sem:
            return "empty"

        total = len(sem)
        filled = sum([1 for s in sem if s.get("sem_name") and s.get("marks")])

        if filled == 0:
            return "empty"
        elif filled < total:
            return "partial"
        else:
            return "complete"

    # -------- STEP 4 INTERNSHIP --------
    if step == 4:
        required = [d.get("intern_company"), d.get("intern_role")]
        filled = sum([1 for x in required if x])

        if filled == 0:
            return "empty"
        elif filled < len(required):
            return "partial"
        else:
            return "complete"

    # -------- STEP 5 PLACEMENT --------
    if step == 5:
        if d.get("Placed") == "Yes":
            required = [d.get("company"), d.get("role")]
            filled = sum([1 for x in required if x])

            if filled == 0:
                return "empty"
            elif filled < len(required):
                return "partial"
            else:
                return "complete"
        else:
            return "complete"

    return "empty"
    
def calculate_completion():
    done = 0
    for i in range(1,6):
        if get_section_status(i) == "complete":
            done += 1
    return int((done/5)*100)

# ================= NAVIGATION =================

cols = st.columns(6)

for i in range(1,7):
    status = get_section_status(i)
    if status == "complete":
    color = "#28a745"      # Green
elif status == "partial":
    color = "#ffc107"      # Amber
else:
    color = "#dc3545"      # Red

    if cols[i-1].button(steps[i-1]):
        st.session_state.step = i
        st.rerun()

    cols[i-1].markdown(
        f"<div style='height:5px;background:{color};border-radius:3px'></div>",
        unsafe_allow_html=True
    )

# ================= STEP 1 =================

if st.session_state.step == 1:

    app_id = st.text_input("Application ID")

    if st.button("Fetch Data"):
        data = fetch_application_data(app_id)
        if data:
            st.session_state.student_data.update(data)
            st.success("Data Fetched Successfully")
        else:
            st.error("Application ID Not Found")

    name = st.text_input("Name", st.session_state.student_data.get("Name",""))
    mobile = st.text_input("Mobile", st.session_state.student_data.get("Mobile",""))
    email = st.text_input("Email", st.session_state.student_data.get("Email",""))
    loan_amount = st.text_input("Loan Amount", st.session_state.student_data.get("LoanAmount",""))
    course_name = st.text_input("Course Name", st.session_state.student_data.get("CourseName",""))
    current_state = st.text_input("Current State", st.session_state.student_data.get("CurrentState",""))

    st.session_state.student_data.update({
        "Application_ID": app_id,
        "Name": name,
        "Mobile": mobile,
        "Email": email,
        "LoanAmount": loan_amount,
        "CourseName": course_name,
        "CurrentState": current_state
    })

# ================= STEP 2 =================

elif st.session_state.step == 2:

    st.subheader("10th Details")

    school_10 = st.text_input(
        "School Name (10th)",
        value=st.session_state.student_data.get("school_10","")
    )

    board_10 = st.text_input(
        "Board (10th)",
        value=st.session_state.student_data.get("board_10","")
    )

    year_10_value = st.session_state.student_data.get("year_10", "Select Year")
    year_10 = st.selectbox(
        "Year of Passing (10th)",
        year_options,
        index=year_options.index(year_10_value) if year_10_value in year_options else 0
    )

    marks_10 = st.text_input(
        "Percentage / Marks (10th)",
        value=st.session_state.student_data.get("marks_10","")
    )

    doc_10_new = st.file_uploader("Upload 10th Marksheet", key="doc_10")

    if doc_10_new is not None:
     st.session_state.student_data["doc_10"] = doc_10_new

    doc_10 = st.session_state.student_data.get("doc_10")

    # ---------------- 12th ----------------

    st.subheader("12th Details")

    school_12 = st.text_input(
        "School Name (12th)",
        value=st.session_state.student_data.get("school_12","")
    )

    board_12 = st.text_input(
        "Board (12th)",
        value=st.session_state.student_data.get("board_12","")
    )

    year_12_value = st.session_state.student_data.get("year_12", "Select Year")
    year_12 = st.selectbox(
        "Year of Passing (12th)",
        year_options,
        index=year_options.index(year_12_value) if year_12_value in year_options else 0
    )

    marks_12 = st.text_input(
        "Percentage / Marks (12th)",
        value=st.session_state.student_data.get("marks_12","")
    )

    doc_12_new = st.file_uploader("Upload 12th Marksheet", key="doc_12")

    if doc_12_new is not None:
     st.session_state.student_data["doc_12"] = doc_12_new

    doc_12 = st.session_state.student_data.get("doc_12")

    # ---------------- Graduation ----------------

    st.subheader("Graduation Details")

    college_grad = st.text_input(
        "College Name (Graduation)",
        value=st.session_state.student_data.get("college_grad","")
    )

    university_grad = st.text_input(
        "University Name",
        value=st.session_state.student_data.get("university_grad","")
    )

    year_grad_value = st.session_state.student_data.get("year_grad", "Select Year")
    year_grad = st.selectbox(
        "Year of Passing (Graduation)",
        year_options,
        index=year_options.index(year_grad_value) if year_grad_value in year_options else 0
    )

    marks_grad = st.text_input(
        "Final Percentage / CGPA",
        value=st.session_state.student_data.get("marks_grad","")
    )

    doc_grad_new = st.file_uploader("Upload Graduation Marksheet", key="doc_grad")

    if doc_grad_new is not None:
     st.session_state.student_data["doc_grad"] = doc_grad_new

    doc_grad = st.session_state.student_data.get("doc_grad")

    # ---------------- Competitive Exam ----------------

    st.subheader("Competitive Exam Details")

    exam_name = st.text_input(
        "Exam Name",
        value=st.session_state.student_data.get("exam_name","")
    )

    exam_year_value = st.session_state.student_data.get("exam_year", "Select Year")
    exam_year = st.selectbox(
        "Exam Year",
        year_options,
        index=year_options.index(exam_year_value) if exam_year_value in year_options else 0
    )

    exam_score = st.text_input(
        "Score",
        value=st.session_state.student_data.get("exam_score","")
    )

    exam_rank = st.text_input(
        "Rank",
        value=st.session_state.student_data.get("exam_rank","")
    )

    exam_doc_new = st.file_uploader("Upload Scorecard", key="exam_doc")

    if exam_doc_new is not None:
     st.session_state.student_data["exam_doc"] = exam_doc_new

    exam_doc = st.session_state.student_data.get("exam_doc")

    st.session_state.student_data.update({
        "school_10": school_10,
        "board_10": board_10,
        "year_10": year_10,
        "marks_10": marks_10,
        "doc_10": doc_10,

        "school_12": school_12,
        "board_12": board_12,
        "year_12": year_12,
        "marks_12": marks_12,
        "doc_12": doc_12,

        "college_grad": college_grad,
        "university_grad": university_grad,
        "year_grad": year_grad,
        "marks_grad": marks_grad,
        "doc_grad": doc_grad,

        "exam_name": exam_name,
        "exam_year": exam_year,
        "exam_score": exam_score,
        "exam_rank": exam_rank,
        "exam_doc": exam_doc
    })

# ================= STEP 3 =================
elif st.session_state.step == 3:

    st.subheader("Course Progression - Semester Wise")

    semester_data = st.session_state.student_data.get("semester_data", [])

    updated_semesters = []

    for i in range(1, st.session_state.semester_count + 1):

        st.markdown(f"### Semester {i}")

        existing = semester_data[i-1] if len(semester_data) >= i else {}

        sem_name = st.text_input(
            f"Semester {i} Name",
            value=existing.get("sem_name",""),
            key=f"sem_name_{i}"
        )

        sem_marks = st.text_input(
            f"Semester {i} Percentage / CGPA",
            value=existing.get("marks",""),
            key=f"sem_marks_{i}"
        )

        sem_doc = st.file_uploader(
            f"Semester {i} Marksheet",
            key=f"sem_doc_{i}"
        )

        updated_semesters.append({
            "sem_no": i,
            "sem_name": sem_name,
            "marks": sem_marks,
            "doc": sem_doc if sem_doc else existing.get("doc")
        })

    st.session_state.student_data["semester_data"] = updated_semesters

    colA, colB = st.columns(2)

    with colA:
        if st.button("➕ Add Semester"):
            if st.session_state.semester_count < 10:
                st.session_state.semester_count += 1
                st.rerun()

    with colB:
        if st.button("➖ Remove Semester"):
            if st.session_state.semester_count > 1:
                st.session_state.semester_count -= 1
                st.rerun()

# ================= STEP 4 =================

elif st.session_state.step == 4:

    st.subheader("Internship Details")

    intern_company = st.text_input(
        "Internship Company",
        value=st.session_state.student_data.get("intern_company","")
    )

    intern_role = st.text_input(
        "Role",
        value=st.session_state.student_data.get("intern_role","")
    )

    intern_duration = st.text_input(
        "Duration",
        value=st.session_state.student_data.get("intern_duration","")
    )

    intern_doc_new = st.file_uploader("Internship Certificate", key="intern_doc")

    if intern_doc_new is not None:
     st.session_state.student_data["intern_doc"] = intern_doc_new

    intern_doc = st.session_state.student_data.get("intern_doc")

    st.session_state.student_data.update({
        "intern_company": intern_company,
        "intern_role": intern_role,
        "intern_duration": intern_duration,
        "intern_doc": intern_doc if intern_doc else st.session_state.student_data.get("intern_doc")
    })

# ================= STEP 5 =================

elif st.session_state.step == 5:

    st.subheader("Placement Details")

    placed_value = st.session_state.student_data.get("Placed", "No")

    placed = st.selectbox(
        "Placed?",
        ["No", "Yes"],
        index=["No", "Yes"].index(placed_value)
    )

    st.session_state.student_data["Placed"] = placed

    if placed == "Yes":

        company = st.text_input(
            "Company",
            value=st.session_state.student_data.get("company", "")
        )

        role = st.text_input(
            "Role",
            value=st.session_state.student_data.get("role", "")
        )

        # ===== OFFER LETTER =====
        offer_new = st.file_uploader("Offer Letter", key="offer_doc")

        if offer_new is not None:
            st.session_state.student_data["offer_doc"] = offer_new

        offer_doc = st.session_state.student_data.get("offer_doc")

        if offer_doc:
            st.success("Offer Letter Uploaded ✅")

        # ===== ADDRESS PROOF =====
        address_new = st.file_uploader("Address Proof", key="address_doc")

        if address_new is not None:
            st.session_state.student_data["address_doc"] = address_new

        address_doc = st.session_state.student_data.get("address_doc")

        if address_doc:
            st.success("Address Proof Uploaded ✅")

        # ===== RESUME =====
        resume_new = st.file_uploader("Upload Resume", key="resume_doc")

        if resume_new is not None:
            st.session_state.student_data["resume_doc"] = resume_new

        resume_doc = st.session_state.student_data.get("resume_doc")

        if resume_doc:
            st.success("Resume Uploaded ✅")

        st.session_state.student_data.update({
            "company": company,
            "role": role
        })

# ================= STEP 6 =================
elif st.session_state.step == 6:

    st.subheader("📋 Complete Application Review")

    data = st.session_state.student_data

    # -------- BASIC --------
    st.markdown("### 🧾 Basic Information")
    st.write("Application ID:", data.get("Application_ID",""))
    st.write("Name:", data.get("Name",""))
    st.write("Mobile:", data.get("Mobile",""))
    st.write("Email:", data.get("Email",""))
    st.write("Loan Amount:", data.get("LoanAmount",""))
    st.write("Course:", data.get("CourseName",""))
    st.write("Current State:", data.get("CurrentState",""))

    st.markdown("---")

    # -------- EDUCATION --------
    st.markdown("### 🎓 Education Details")

    st.write("10th:", data.get("school_10",""), "-", data.get("marks_10",""))
    st.write("12th:", data.get("school_12",""), "-", data.get("marks_12",""))
    st.write("Graduation:", data.get("college_grad",""), "-", data.get("marks_grad",""))
    st.write("Competitive Exam:", data.get("exam_name",""), "-", data.get("exam_score",""))

    st.markdown("---")

    # -------- SEMESTER --------
    st.markdown("### 📚 Semester Details")

    for sem in data.get("semester_data", []):
        st.write(f"{sem.get('sem_name','')} - {sem.get('marks','')}")

    st.markdown("---")

    # -------- INTERNSHIP --------
    st.markdown("### 💼 Internship")

    st.write("Company:", data.get("intern_company",""))
    st.write("Role:", data.get("intern_role",""))
    st.write("Duration:", data.get("intern_duration",""))

    st.markdown("---")

    # -------- PLACEMENT --------
    st.markdown("### 🏢 Placement")

    st.write("Placed:", data.get("Placed",""))

    if data.get("Placed") == "Yes":
        st.write("Company:", data.get("company",""))
        st.write("Role:", data.get("role",""))

    st.markdown("---")

    # -------- FINAL SUBMIT --------
    if st.button("✅ Final Submit"):

        try:
            folder_name = f"{data.get('Application_ID','')}_{data.get('Name','')}"
            folder_id = create_student_folder(folder_name)
            folder_link = f"https://drive.google.com/drive/folders/{folder_id}"

            uploaded_links = {}

            # Upload normal files
            for key, value in data.items():
                if hasattr(value, "type"):
                    link = upload_file_to_drive(value, folder_id, key)
                    uploaded_links[key] = link

            # Upload semester files
            for sem in data.get("semester_data", []):
                if hasattr(sem.get("doc"), "type"):
                    link = upload_file_to_drive(
                        sem.get("doc"),
                        folder_id,
                        f"Semester_{sem.get('sem_no')}"
                    )
                    uploaded_links[f"Semester_{sem.get('sem_no')}"] = link

            save_to_sheet(data, folder_link, uploaded_links)

            st.success("🎉 Application Submitted Successfully!")
            st.write("Drive Folder:", folder_link)

        except Exception as e:
            st.error(f"Submission Failed: {e}")
# ================= BOTTOM NAV =================

c1,c2=st.columns(2)

if c1.button("⬅ Back") and st.session_state.step>1:
    st.session_state.step-=1
    st.rerun()

if c2.button("Next ➡") and st.session_state.step<6:
    st.session_state.step+=1

    st.rerun()

