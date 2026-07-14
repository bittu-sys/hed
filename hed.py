import streamlit as st
import pandas as pd
import os
import io
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import re

# ================= FILE SIZE LIMIT =================
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

def validate_file(uploaded_file):
    if uploaded_file is not None:
        if uploaded_file.size > MAX_FILE_SIZE:
            st.error(
                f"❌ '{uploaded_file.name}' "
                f"exceeds 5MB limit. "
                f"Please upload a smaller file."
            )
            return None
        return uploaded_file
    return None

# ================= CONFIG =================

FOLDER_ID = "0AKQoF-VACGZsUk9PVA"
SHEET_ID = "1An8HEEx-pDJso87QkZSlE5Ot3yW9sl-59k7XQwQ7iic"
SAVE_TAB = "HED_SUBMISSIONS_NEW"

SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets'
]

# ================= YEAR OPTIONS =================

year_options = ["Select Year"] + [str(y) for y in range(2000, datetime.now().year + 1)]

# ================= DROPDOWN OPTIONS =================

marks_type_options = ["Select", "Percentage (%)", "CGPA", "Actual Marks"]

states_list = [
"Select State","Andhra Pradesh","Arunachal Pradesh","Assam","Bihar","Chhattisgarh",
"Goa","Gujarat","Haryana","Himachal Pradesh","Jharkhand","Karnataka","Kerala",
"Madhya Pradesh","Maharashtra","Manipur","Meghalaya","Mizoram","Nagaland",
"Odisha","Punjab","Rajasthan","Sikkim","Tamil Nadu","Telangana","Tripura",
"Uttar Pradesh","Uttarakhand","West Bengal","Andaman and Nicobar Islands","Chandigarh",
"Dadra and Nagar Haveli and Daman and Diu","Delhi","Jammu and Kashmir","Ladakh","Lakshadweep","Puducherry"
]

country_list = [
"Select Country","India","USA","UK","Canada","Australia","Germany","France",
"Singapore","UAE","Switzerland","Netherlands","Denmark","New Zealand","Other"
]

credentials = service_account.Credentials.from_service_account_info(
    st.secrets["gcp_service_account"],
    scopes=SCOPES
)

drive_service = build('drive', 'v3', credentials=credentials)
sheet_service = build('sheets', 'v4', credentials=credentials)

# ================= SESSION INIT =================

def init_session():
    defaults = {
        "step": 1,
        "student_data": {},
        "semester_count": 1,
        "submitted": False,
        "drive_folder_id": None,
        "existing_row_index": None,
        # KEY FIX: file_store stores bytes so files survive page navigation
        # Structure: { key: {"bytes": b"...", "name": "file.pdf", "type": "application/pdf"} }
        "file_store": {},
        # saved_links: links already in Google Sheet for this application
        # Structure: { "doc_10": "https://...", "folder_link": "https://...", ... }
        "saved_links": {},
        "last_submit_success": None,
        "data_fetched": False,
        "fetch_app_id": "",
        "fetch_tranche": "",
        "data_fetched": False,
        "allow_next": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session()

def reset_student_data(app_id, tranche_number):
    """
    Blank form for new tranche / new application.
    Prevents previous tranche data from remaining in session.
    """

    st.session_state.student_data = {

        # Basic
        "Application_ID": app_id,
        "TrancheNumber": tranche_number,

        "Name": "",
        "Mobile": "",
        "Email": "",
        "CourseName": "",
        "CurrentLoanStatus": "",
        "SanctionLoanAmount": "",
        "DisbursementTrancheAmount": "",

        # Education
        "school_10": "",
        "board_10": "",
        "state_10": "Select State",
        "year_10": "Select Year",
        "marks_type_10": "Select",
        "marks_10": "",

        "school_12": "",
        "board_12": "",
        "state_12": "Select State",
        "year_12": "Select Year",
        "marks_type_12": "Select",
        "marks_12": "",

        "HasGraduation": "No",
        "college_grad": "",
        "university_grad": "",
        "state_grad": "Select State",
        "year_grad": "Select Year",
        "marks_type_grad": "Select",
        "marks_grad": "",

        "HasPostGraduation": "No",
        "pg_college": "",
        "pg_university": "",
        "pg_state": "Select State",
        "pg_year": "Select Year",
        "pg_marks_type": "Select",
        "pg_marks": "",

        "HasOtherCourse": "No",
        "other_course_name": "",
        "other_institute_name": "",
        "other_course_completion_year": "Select Year",
        "other_course_marks": "",

        "HasCompetitiveExam": "No",
        "exam_name": "",
        "exam_year": "Select Year",
        "exam_score": "",
        "exam_rank": "",

        # Semester
        "ug_semester_data": [],
        "pg_semester_data": [],

        # Internship
        "intern_company": "",
        "intern_role": "",
        "intern_duration": "",
        "intern_state": "Select State",

        # Placement
        "Placed": "No",
        "company": "",
        "role": "",
        "ctc": "",
        "current_address": "",
        "country": "Select Country"
    }

    st.session_state.saved_links = {}
    st.session_state.file_store = {}
    st.session_state.drive_folder_id = None
    st.session_state.existing_row_index = None
    st.session_state.semester_count = 1
    st.session_state.last_submit_success = None


# ================= FILE PERSISTENCE HELPERS =================
# PROBLEM: Streamlit's file_uploader widget returns None when user navigates
# away and comes back. We fix this by immediately reading bytes into
# session_state["file_store"] so they survive reruns and page switches.

def persist_file(key, uploaded_file):
    """
    If a new file is uploaded, save its bytes to file_store immediately.
    Never deletes existing stored file — only overwrites if new file provided.
    """
    if uploaded_file is not None:
        st.session_state.file_store[key] = {
            "bytes": uploaded_file.getvalue(),
            "name":  uploaded_file.name,
            "type":  uploaded_file.type,
        }


def get_stored_file(key):
    """
    Return a BytesIO object (with .name and .type) for the stored file,
    or None if nothing is stored for this key.
    """
    entry = st.session_state.file_store.get(key)
    if not entry:
        return None
    buf      = io.BytesIO(entry["bytes"])
    buf.name = entry["name"]
    buf.type = entry["type"]
    return buf


def file_status_display(
    key,
    saved_link,
    label
):
    """
    Show document upload status
    """

    # New uploaded in current session
    if key in st.session_state.file_store:

        file_name = (
            st.session_state
            .file_store[key]["name"]
        )

        st.success(
            f"✅ {label} uploaded: {file_name}"
        )

        return

    # Existing document already in drive
    if saved_link and str(saved_link).strip():

        st.success(
            f"✅ {label} already uploaded"
        )

        st.markdown(
            f"🔗 [Open Existing Document]({saved_link})"
        )

        return

    # Missing
    st.warning(
        f"⚠️ {label} — not uploaded yet"
    )

def validate_all_uploaded_files():
    """
    Check all uploaded files are <= 5MB.
    Return list of invalid files.
    """
    invalid_files = []

    for key, file_info in st.session_state.file_store.items():

        file_size = len(file_info["bytes"])

        if file_size > MAX_FILE_SIZE:

            size_mb = round(
                file_size / (1024 * 1024),
                2
            )

            invalid_files.append(
                (
                    key,
                    file_info["name"],
                    size_mb
                )
            )

    return invalid_files


# ================= GOOGLE SHEET HELPERS =================

def fetch_existing_submission(app_id, tranche_number):
    """Fetch existing row using Application_ID + TrancheNumber"""
    result = sheet_service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"{SAVE_TAB}!A:ZZ"
    ).execute()
    values = result.get("values", [])
    if not values:
        return None, None, None
    header = values[0]
    try:
        tranche_col = header.index("TrancheNumber")
    except ValueError:
        tranche_col = 6    
    for idx, row in enumerate(values[1:], start=2):
        row_app = row[0] if len(row) > 0 else ""
        row_tranche = row[tranche_col] if len(row) > tranche_col else ""

        if (
        str(row_app).strip() == str(app_id).strip()
        and
        str(row_tranche).strip() == str(tranche_number).strip()
        ):
            return idx, row, header
    return None, None, None


def parse_existing_row(row_data, header_row):
    """
    Parse existing Google Sheet row into student_data and saved_links.
    Header based parsing so column order can change safely.
    """

    # ================= HEADER MAP =================

    hmap = {}

    for idx, h in enumerate(header_row):
        hmap[str(h).strip().lower()] = idx

    def ph(header_name):
        idx = hmap.get(str(header_name).strip().lower())

        if idx is None:
            return ""

        return row_data[idx] if idx < len(row_data) else ""

    # ================= STUDENT DATA =================

    student_data = {

        # ---------- BASIC ----------

        "Application_ID": ph("Application_ID"),
        "Name": ph("Name"),
        "Mobile": ph("Mobile"),
        "Email": ph("Email"),

        "CourseName": ph("CourseName"),
        "CurrentLoanStatus": ph("CurrentLoanStatus"),

        "TrancheNumber": ph("TrancheNumber"),
        "SanctionLoanAmount": ph("SanctionLoanAmount"),
        "DisbursementTrancheAmount": ph("DisbursementTrancheAmount"),

        # ---------- 10TH ----------

        "school_10": ph("10th School"),
        "board_10": ph("10th Board"),
        "state_10": ph("10th State"),
        "year_10": ph("10th Year"),
        "marks_type_10": ph("10th Marks Type"),
        "marks_10": ph("10th Marks"),

        # ---------- 12TH ----------

        "school_12": ph("12th School"),
        "board_12": ph("12th Board"),
        "state_12": ph("12th State"),
        "year_12": ph("12th Year"),
        "marks_type_12": ph("12th Marks Type"),
        "marks_12": ph("12th Marks"),

        # ---------- GRAD ----------

        "HasGraduation": ph("HasGraduation"),
        "college_grad": ph("Graduation College"),
        "university_grad": ph("University"),
        "state_grad": ph("Graduation State"),
        "year_grad": ph("Grad Year"),
        "marks_type_grad": ph("Grad Marks Type"),
        "marks_grad": ph("Grad Marks"),

        # ---------- PG ----------

        "HasPostGraduation": ph("HasPostGraduation"),

        "pg_college": ph("PG College"),
        "pg_university": ph("PG University"),
        "pg_state": ph("PG State"),
        "pg_year": ph("PG Year"),
        "pg_marks_type": ph("PG Marks Type"),
        "pg_marks": ph("PG Marks"),

        # ---------- OTHER COURSE ----------

        "HasOtherCourse": ph("HasOtherCourse"),
        "other_course_name": ph("Other Course Name"),
        "other_institute_name": ph("Other Institute Name"),
        "other_course_completion_year": ph("Other Course Completion Year"),
        "other_course_marks": ph("Other Course Marks"),

        # ---------- EXAM ----------

        "HasCompetitiveExam": ph("HasCompetitiveExam"),
        "exam_name": ph("Exam Name"),
        "exam_year": ph("Exam Year"),
        "exam_score": ph("Exam Score"),
        "exam_rank": ph("Exam Rank"),

        # ---------- INTERNSHIP ----------

        "intern_company": ph("Intern Company"),
        "intern_role": ph("Intern Role"),
        "intern_duration": ph("Intern Duration"),
        "intern_state": ph("Intern State"),

        # ---------- PLACEMENT ----------

        "Placed": ph("Placed"),
        "company": ph("Company"),
        "role": ph("Role"),
        "ctc": ph("CTC"),
        "current_address": ph("Current Address"),
        "country": ph("Country"),
    }
    
        # ================= UG SEMESTERS =================

    ug_semesters = []

    for i in range(1, 9):

        sem = {
            "sem_no": i,
            "college": ph(f"ug_sem{i}_college"),
            "course": ph(f"ug_sem{i}_course"),
            "year": ph(f"ug_sem{i}_year"),
            "marks_type": ph(f"ug_sem{i}_marks_type"),
            "marks": ph(f"ug_sem{i}_marks"),
            "state": ph(f"ug_sem{i}_state")
        }

        if any([
            sem["college"],
            sem["course"],
            sem["year"],
            sem["marks_type"],
            sem["marks"],
            sem["state"]
        ]):
            ug_semesters.append(sem)

    student_data["ug_semester_data"] = ug_semesters


    # ================= PG SEMESTERS =================

    pg_semesters = []

    for i in range(1, 9):

        sem = {
            "sem_no": i,
            "college": ph(f"pg_sem{i}_college"),
            "course": ph(f"pg_sem{i}_course"),
            "year": ph(f"pg_sem{i}_year"),
            "marks_type": ph(f"pg_sem{i}_marks_type"),
            "marks": ph(f"pg_sem{i}_marks"),
            "state": ph(f"pg_sem{i}_state")
        }

        if any([
            sem["college"],
            sem["course"],
            sem["year"],
            sem["marks_type"],
            sem["marks"],
            sem["state"]
        ]):
            pg_semesters.append(sem)

    student_data["pg_semester_data"] = pg_semesters

        # ================= SAVED LINKS =================

    saved_links = {

        "folder_link": ph("DriveFolderLink"),

        # Education Docs
        "doc_10": ph("doc_10"),
        "doc_12": ph("doc_12"),
        "doc_grad": ph("doc_grad"),
        "doc_pg": ph("doc_pg"),
        "other_course_doc": ph("other_course_doc"),
        "exam_doc": ph("exam_doc"),

        # UG Semester Docs
        "UG_Semester_1": ph("UG_Semester_1"),
        "UG_Semester_2": ph("UG_Semester_2"),
        "UG_Semester_3": ph("UG_Semester_3"),
        "UG_Semester_4": ph("UG_Semester_4"),
        "UG_Semester_5": ph("UG_Semester_5"),
        "UG_Semester_6": ph("UG_Semester_6"),
        "UG_Semester_7": ph("UG_Semester_7"),
        "UG_Semester_8": ph("UG_Semester_8"),

        # PG Semester Docs
        "PG_Semester_1": ph("PG_Semester_1"),
        "PG_Semester_2": ph("PG_Semester_2"),
        "PG_Semester_3": ph("PG_Semester_3"),
        "PG_Semester_4": ph("PG_Semester_4"),
        "PG_Semester_5": ph("PG_Semester_5"),
        "PG_Semester_6": ph("PG_Semester_6"),
        "PG_Semester_7": ph("PG_Semester_7"),
        "PG_Semester_8": ph("PG_Semester_8"),

        # Other Docs
        "intern_doc": ph("intern_doc"),
        "offer_doc": ph("offer_doc"),
        "address_doc": ph("address_doc"),
        "resume_doc": ph("resume_doc"),
    }

    # Remove blank values
    saved_links = {
        k: v
        for k, v in saved_links.items()
        if str(v).strip()
    }

    # ================= DEBUG =================

    st.session_state["_debug_headers"] = list(header_row)
    st.session_state["_debug_hmap"] = hmap
    st.session_state["_debug_saved_links"] = dict(saved_links)
    st.session_state["_debug_total_cols"] = len(header_row)

    folder_col_idx = hmap.get("drivefolderlink")
    st.session_state["_debug_folder_col_idx"] = folder_col_idx

    # ================= RETURN =================

    return student_data, saved_links

# ================= DRIVE HELPERS =================

def get_folder_id_from_link(link):
    """Extract folder ID from a Google Drive folder URL."""
    if not link:
        return None
    try:
        match = re.search(r'folders/([a-zA-Z0-9_-]+)', str(link).strip())
        if match:
            return match.group(1)
    except Exception:
        pass
    return None

def get_file_id_from_link(link):
    """Extract file ID from Google Drive file URL."""
    if not link:
        return None

    try:
        match = re.search(
            r'/d/([a-zA-Z0-9_-]+)',
            str(link).strip()
        )

        if match:
            return match.group(1)

    except Exception:
        pass

    return None


def create_student_folder(folder_name):
    """Create a new folder inside FOLDER_ID and return its ID."""
    file_metadata = {
        'name':     folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents':  [FOLDER_ID]
    }
    folder = drive_service.files().create(
        body=file_metadata,
        fields='id',
        supportsAllDrives=True,
        supportsTeamDrives=True
    ).execute()
    return folder.get('id')


def upload_file_to_drive(
    file_obj,
    folder_id,
    filename,
    existing_link=None
):

    if not folder_id:
        raise Exception(
            "Folder ID missing."
        )

    media = MediaIoBaseUpload(
        file_obj,
        mimetype=file_obj.type,
        resumable=False
    )

    existing_file_id = (
        get_file_id_from_link(
            existing_link
        )
    )

    # Update existing file
    if existing_file_id:
        updated = (
            drive_service.files()
            .update(
                fileId=existing_file_id,
                media_body=media,
                supportsAllDrives=True
            )
            .execute()
        )

        return (
            f"https://drive.google.com/file/d/"
            f"{updated['id']}/view"
        )

    # Create new file
    file_metadata = {
        "name": filename,
        "parents": [folder_id]
    }

    uploaded = (
        drive_service.files()
        .create(
            body=file_metadata,
            media_body=media,
            fields="id",
            supportsAllDrives=True
        )
        .execute()
    )

    return (
        f"https://drive.google.com/file/d/"
        f"{uploaded['id']}/view"
    )


def find_existing_drive_folder(app_id, name, tranche):
    """
    Search Drive for an existing folder named AppID_Name inside FOLDER_ID.
    Returns folder_id if found, else None.
    """
    try:
        folder_name = f"{app_id}_TRANCHE_{tranche}"
        query = (
            f"name='{folder_name}' "
            f"and mimeType='application/vnd.google-apps.folder' "
            f"and '{FOLDER_ID}' in parents "
            f"and trashed=false"
        )
        result = drive_service.files().list(
            q=query,
            fields="files(id, name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        files = result.get("files", [])
        if files:
            return files[0]["id"]
    except Exception as e:
        st.warning(f"Drive search error: {e}")
    return None


def resolve_or_create_folder(data):
    """
    Folder resolution — 4 priority levels:

    1. Already cached in session this run → reuse
    2. Link exists in sheet (saved_links) → parse and use
    3. No link in sheet → search Drive by folder name (AppID_Name)
       This handles old submissions where link was never saved to sheet
    4. Not found anywhere → create new folder (truly new application)
    """
    app_id = data.get("Application_ID", "")
    name   = data.get("Name", "")

    # ── Priority 1: already resolved this session ──────────────────────
    current_app = data.get("Application_ID")
    current_tranche = data.get("TrancheNumber")
    if (
        st.session_state.fetch_app_id == current_app
        and
        st.session_state.fetch_tranche == current_tranche
        and
        st.session_state.drive_folder_id
    ):
        return st.session_state.drive_folder_id

    # ── Priority 2: link in sheet ───────────────────────────────────────
    folder_link = st.session_state.saved_links.get("folder_link", "")
    folder_id   = get_folder_id_from_link(folder_link)
    if folder_id:
        st.session_state.drive_folder_id = folder_id
        return folder_id

    # ── Priority 3: search Drive by name (old submissions, link missing) ─
    if (st.session_state.get("existing_row_index") is not None or app_id):
        found_id = find_existing_drive_folder(app_id, name,data.get("TrancheNumber", ""))
        if found_id:
            st.info(f"📁 Existing Drive folder found by name search.")
            st.session_state.drive_folder_id = found_id
            # Also update saved_links so folder link gets written to sheet on save
            st.session_state.saved_links["folder_link"] = (
                f"https://drive.google.com/drive/folders/{found_id}"
            )
            return found_id

    # ── Priority 4: create new folder ──────────────────────────────────
    tranche = data.get("TrancheNumber", "")
    folder_name = f"{app_id}_TRANCHE_{tranche}"
    new_folder_id = create_student_folder(folder_name)
    st.session_state.drive_folder_id = new_folder_id
    return new_folder_id


# ================= SHEET WRITE HELPERS =================

def clean_value(val):
    if val in ["Select", "Select State", "Select Year", "Select Country"]:
        return ""
    return val


# ── FULL expected header row (must match build_row_values column order) ──
EXPECTED_HEADERS = [
"Application_ID",
"Name",
"Mobile",
"Email",
"CourseName",
"CurrentLoanStatus",
"TrancheNumber",
"SanctionLoanAmount",
"DisbursementTrancheAmount",

"10th School",
"10th Board",
"10th State",
"10th Year",
"10th Marks Type",
"10th Marks",

"12th School",
"12th Board",
"12th State",
"12th Year",
"12th Marks Type",
"12th Marks",

"HasGraduation",
"Graduation College",
"University",
"Graduation State",
"Grad Year",
"Grad Marks Type",
"Grad Marks",

"HasPostGraduation",
"PG College",
"PG University",
"PG State",
"PG Year",
"PG Marks Type",
"PG Marks",

"HasOtherCourse",
"Other Course Name",
"Other Institute Name",
"Other Course Completion Year",
"Other Course Marks",

"HasCompetitiveExam",
"Exam Name",
"Exam Year",
"Exam Score",
"Exam Rank",

"ug_sem1_college",
"ug_sem1_course",
"ug_sem1_year",
"ug_sem1_marks_type",
"ug_sem1_marks",
"ug_sem1_state",

"ug_sem2_college",
"ug_sem2_course",
"ug_sem2_year",
"ug_sem2_marks_type",
"ug_sem2_marks",
"ug_sem2_state",

"ug_sem3_college",
"ug_sem3_course",
"ug_sem3_year",
"ug_sem3_marks_type",
"ug_sem3_marks",
"ug_sem3_state",

"ug_sem4_college",
"ug_sem4_course",
"ug_sem4_year",
"ug_sem4_marks_type",
"ug_sem4_marks",
"ug_sem4_state",

"ug_sem5_college",
"ug_sem5_course",
"ug_sem5_year",
"ug_sem5_marks_type",
"ug_sem5_marks",
"ug_sem5_state",

"ug_sem6_college",
"ug_sem6_course",
"ug_sem6_year",
"ug_sem6_marks_type",
"ug_sem6_marks",
"ug_sem6_state",

"ug_sem7_college",
"ug_sem7_course",
"ug_sem7_year",
"ug_sem7_marks_type",
"ug_sem7_marks",
"ug_sem7_state",

"ug_sem8_college",
"ug_sem8_course",
"ug_sem8_year",
"ug_sem8_marks_type",
"ug_sem8_marks",
"ug_sem8_state",

"pg_sem1_college",
"pg_sem1_course",
"pg_sem1_year",
"pg_sem1_marks_type",
"pg_sem1_marks",
"pg_sem1_state",

"pg_sem2_college",
"pg_sem2_course",
"pg_sem2_year",
"pg_sem2_marks_type",
"pg_sem2_marks",
"pg_sem2_state",

"pg_sem3_college",
"pg_sem3_course",
"pg_sem3_year",
"pg_sem3_marks_type",
"pg_sem3_marks",
"pg_sem3_state",

"pg_sem4_college",
"pg_sem4_course",
"pg_sem4_year",
"pg_sem4_marks_type",
"pg_sem4_marks",
"pg_sem4_state",

"pg_sem5_college",
"pg_sem5_course",
"pg_sem5_year",
"pg_sem5_marks_type",
"pg_sem5_marks",
"pg_sem5_state",

"pg_sem6_college",
"pg_sem6_course",
"pg_sem6_year",
"pg_sem6_marks_type",
"pg_sem6_marks",
"pg_sem6_state",

"pg_sem7_college",
"pg_sem7_course",
"pg_sem7_year",
"pg_sem7_marks_type",
"pg_sem7_marks",
"pg_sem7_state",

"pg_sem8_college",
"pg_sem8_course",
"pg_sem8_year",
"pg_sem8_marks_type",
"pg_sem8_marks",
"pg_sem8_state",

"Intern Company",
"Intern Role",
"Intern Duration",
"Intern State",

"Placed",
"Company",
"Role",
"CTC",

"Current Address",
"Country",

"DriveFolderLink",

"doc_10",
"doc_12",
"doc_grad",
"doc_pg",
"other_course_doc",
"exam_doc",

"UG_Semester_1",
"UG_Semester_2",
"UG_Semester_3",
"UG_Semester_4",
"UG_Semester_5",
"UG_Semester_6",
"UG_Semester_7",
"UG_Semester_8",

"PG_Semester_1",
"PG_Semester_2",
"PG_Semester_3",
"PG_Semester_4",
"PG_Semester_5",
"PG_Semester_6",
"PG_Semester_7",
"PG_Semester_8",

"intern_doc",
"offer_doc",
"address_doc",
"resume_doc",

"FormStatus",
"SubmittedAt"
]


def ensure_sheet_headers():
    """
    Ensure header row in HED_SUBMISSIONS has ALL expected columns.

    Strategy:
    - Read current header row
    - Build a set of existing header names (lowercase)
    - For any expected header not present, append it after the last column
    This NEVER shifts existing columns — only adds new ones at the end.
    So existing data rows are never misaligned.
    """
    try:
        result = sheet_service.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range=f"{SAVE_TAB}!1:1"
        ).execute()
    except Exception as e:
        st.error(f"❌ Could not READ sheet headers: {e}")
        st.stop()

    existing_headers = result.get("values", [[]])[0]
    existing_set     = {str(h).strip().lower() for h in existing_headers}
    existing_count   = len(existing_headers)

    # Find which expected headers are missing
    missing = [h for h in EXPECTED_HEADERS if h.lower() not in existing_set]
    if not missing:
        return  # All headers present — nothing to do

    # Append only the missing headers after the last existing column
    start_col_letter = col_index_to_letter(existing_count)
    range_notation   = f"{SAVE_TAB}!{start_col_letter}1"

    try:
        sheet_service.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range=range_notation,
            valueInputOption="RAW",
            body={"values": [missing]}
        ).execute()
    except Exception as e:
        # This is almost always a PERMISSIONS problem: the service account
        # can read the sheet but does not have Editor access to write to it.
        # Share the Google Sheet with the service account's client_email
        # (found in st.secrets["gcp_service_account"]["client_email"])
        # as "Editor", not "Viewer".
        service_email = st.secrets.get("gcp_service_account", {}).get("client_email", "unknown")
        st.error(
            f"❌ Could not UPDATE sheet headers.\n\n"
            f"Real error: {e}\n\n"
            f"👉 Most likely cause: the service account ({service_email}) "
            f"only has VIEWER access to this Google Sheet. "
            f"Share the sheet with this email as **Editor** and try again."
        )
        st.stop()


def col_index_to_letter(index):
    """Convert 0-based column index to spreadsheet letter (0=A, 25=Z, 26=AA ...)."""
    result = ""
    index += 1
    while index > 0:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result

def calculate_form_status(data_dict):

    statuses = [get_section_status(i) for i in range(1, 6)]

    ug_semesters = data_dict.get("ug_semester_data", [])
    pg_semesters = data_dict.get("pg_semester_data", [])

    semester_filled = any(
        sem.get("college")
        for sem in ug_semesters
    )

    pg_semester_filled = any(
        sem.get("college")
        for sem in pg_semesters
    )

    if not semester_filled and not pg_semester_filled:
        return "PARTIAL"

    if all(s == "complete" for s in statuses):
        return "COMPLETE"

    if any(s != "empty" for s in statuses):
        return "PARTIAL"

    return "EMPTY"

def build_row_values(data_dict, folder_link, uploaded_links):

    form_status = calculate_form_status(data_dict)

    ug_semesters = {
        s.get("sem_no"): s
        for s in data_dict.get("ug_semester_data", [])
    }

    pg_semesters = {
        s.get("sem_no"): s
        for s in data_dict.get("pg_semester_data", [])
    }

    row = [

        # ================= BASIC =================

        data_dict.get("Application_ID", ""),
        data_dict.get("Name", ""),
        data_dict.get("Mobile", ""),
        data_dict.get("Email", ""),

        data_dict.get("CourseName", ""),
        data_dict.get("CurrentLoanStatus", ""),

        data_dict.get("TrancheNumber", ""),
        data_dict.get("SanctionLoanAmount", ""),
        data_dict.get("DisbursementTrancheAmount", ""),

        # ================= 10TH =================

        data_dict.get("school_10", ""),
        data_dict.get("board_10", ""),
        clean_value(data_dict.get("state_10", "")),
        clean_value(data_dict.get("year_10", "")),
        clean_value(data_dict.get("marks_type_10", "")),
        data_dict.get("marks_10", ""),

        # ================= 12TH =================

        data_dict.get("school_12", ""),
        data_dict.get("board_12", ""),
        clean_value(data_dict.get("state_12", "")),
        clean_value(data_dict.get("year_12", "")),
        clean_value(data_dict.get("marks_type_12", "")),
        data_dict.get("marks_12", ""),

        # ================= GRAD =================

        data_dict.get("HasGraduation", ""),
        data_dict.get("college_grad", ""),
        data_dict.get("university_grad", ""),
        clean_value(data_dict.get("state_grad", "")),
        clean_value(data_dict.get("year_grad", "")),
        clean_value(data_dict.get("marks_type_grad", "")),
        data_dict.get("marks_grad", ""),

        # ================= PG =================

        data_dict.get("HasPostGraduation", ""),

        data_dict.get("pg_college", ""),
        data_dict.get("pg_university", ""),
        clean_value(data_dict.get("pg_state", "")),
        clean_value(data_dict.get("pg_year", "")),
        clean_value(data_dict.get("pg_marks_type", "")),
        data_dict.get("pg_marks", ""),

        # ================= OTHER COURSE =================

        data_dict.get("HasOtherCourse", ""),
        data_dict.get("other_course_name", ""),
        data_dict.get("other_institute_name", ""),
        clean_value(data_dict.get("other_course_completion_year", "")),
        data_dict.get("other_course_marks", ""),

        # ================= EXAM =================

        data_dict.get("HasCompetitiveExam", ""),
        data_dict.get("exam_name", ""),
        clean_value(data_dict.get("exam_year", "")),
        data_dict.get("exam_score", ""),
        data_dict.get("exam_rank", "")
    ]
        # ================= UG SEMESTERS =================

    for sem_no in range(1, 9):

        sem = ug_semesters.get(sem_no, {})

        row.extend([
            sem.get("college", ""),
            sem.get("course", ""),
            clean_value(sem.get("year", "")),
            clean_value(sem.get("marks_type", "")),
            sem.get("marks", ""),
            clean_value(sem.get("state", ""))
        ])


    # ================= PG SEMESTERS =================

    for sem_no in range(1, 9):

        sem = pg_semesters.get(sem_no, {})

        row.extend([
            sem.get("college", ""),
            sem.get("course", ""),
            clean_value(sem.get("year", "")),
            clean_value(sem.get("marks_type", "")),
            sem.get("marks", ""),
            clean_value(sem.get("state", ""))
        ])

            # ================= INTERNSHIP =================

    row.extend([

        data_dict.get("intern_company", ""),
        data_dict.get("intern_role", ""),
        data_dict.get("intern_duration", ""),
        clean_value(data_dict.get("intern_state", ""))

    ])


    # ================= PLACEMENT =================

    row.extend([

        data_dict.get("Placed", ""),

        data_dict.get("company", ""),
        data_dict.get("role", ""),
        data_dict.get("ctc", ""),

        data_dict.get("current_address", ""),
        clean_value(data_dict.get("country", ""))

    ])


    # ================= DRIVE =================

    row.append(folder_link)


    # ================= EDUCATION DOCS =================

    row.extend([

        uploaded_links.get("doc_10", ""),
        uploaded_links.get("doc_12", ""),
        uploaded_links.get("doc_grad", ""),
        uploaded_links.get("doc_pg", ""),
        uploaded_links.get("other_course_doc", ""),
        uploaded_links.get("exam_doc", "")

    ])


    # ================= UG DOCS =================

    for i in range(1, 9):

        row.append(

            uploaded_links.get(f"UG_Semester_{i}", "")
        )

    # ================= PG DOCS =================

    for i in range(1, 9):

        row.append(

            uploaded_links.get(
                f"PG_Semester_{i}",
                ""
            )

        )


    # ================= OTHER DOCS =================

    row.extend([

        uploaded_links.get("intern_doc", ""),
        uploaded_links.get("offer_doc", ""),
        uploaded_links.get("address_doc", ""),
        uploaded_links.get("resume_doc", "")

    ])


    # ================= STATUS =================

    row.extend([

        form_status,

        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    ])


    return row


def save_to_sheet(data_dict, folder_link, uploaded_links):
    values = [build_row_values(data_dict, folder_link, uploaded_links)]
    sheet_service.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range=f"{SAVE_TAB}!A1",
        valueInputOption="RAW",
        body={"values": values}
    ).execute()


def update_sheet_row(row_index, data_dict, folder_link, uploaded_links):
    values = [build_row_values(data_dict, folder_link, uploaded_links)]
    sheet_service.spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"{SAVE_TAB}!A{row_index}",
        valueInputOption="RAW",
        body={"values": values}
    ).execute()


# ================= STATUS ENGINE =================

def get_section_status(step):
    d    = st.session_state.student_data
    saved = st.session_state.saved_links
    fs   = st.session_state.file_store

    if step == 1:
        required = [d.get("Name"), d.get("Mobile"), d.get("Email")]
        filled   = sum(1 for x in required if x)
        if filled == 0:             return "empty"
        if filled < len(required): return "partial"
        return "complete"

    elif step == 2:
        required_fields  = [d.get("school_10"), d.get("marks_10"), d.get("school_12"), d.get("marks_12")]
        doc_10_ok   = bool(fs.get("doc_10"))   or bool(saved.get("doc_10"))
        doc_12_ok   = bool(fs.get("doc_12"))   or bool(saved.get("doc_12"))
        doc_grad_ok = bool(fs.get("doc_grad")) or bool(saved.get("doc_grad"))
        total_required = len(required_fields) + 2
        total_filled   = sum(1 for x in required_fields if x) + int(doc_10_ok)+ int(doc_12_ok)
        if d.get("HasGraduation") == "Yes":
            required_fields.extend([
                d.get("college_grad"),
                d.get("marks_grad")
            ])
            doc_grad_ok = (
                bool(fs.get("doc_grad"))
                or
                bool(saved.get("doc_grad"))
            )
            total_required += 3
            total_filled += (
                sum(1 for x in [d.get("college_grad"), d.get("marks_grad")] if x)+ int(doc_grad_ok)
            )
        if total_filled == 0:               return "empty"
        if total_filled < total_required:   return "partial"
        return "complete"

    elif step == 3:
        sem = d.get("ug_semester_data", [])
        if not sem: return "empty"
        total_required = len(sem) * 2
        filled = 0
        for i, s in enumerate(sem, start=1):
            if s.get("college"): filled += 1
            if fs.get(f"UG_Semester_{i}") or saved.get(f"UG_Semester_{i}"): filled += 1
        if filled == 0:             return "empty"
        if filled < total_required: return "partial"
        return "complete"

    elif step == 4:
        required = [d.get("intern_company"), d.get("intern_role"), fs.get("intern_doc") or saved.get("intern_doc")]
        filled   = sum(1 for x in required if x)
        if filled == 0:             return "empty"
        if filled < len(required):  return "partial"
        return "complete"

    elif step == 5:
        placed = d.get("Placed")
        if not placed:      return "empty"
        if placed == "No":  return "partial"
        if placed == "Yes":
            required_fields = [d.get("company"), d.get("role")]
            offer_ok   = bool(fs.get("offer_doc"))   or bool(saved.get("offer_doc"))
            resume_ok  = bool(fs.get("resume_doc"))  or bool(saved.get("resume_doc"))
            address_ok = bool(fs.get("address_doc")) or bool(saved.get("address_doc"))
            total_filled = sum(1 for x in required_fields if x) + sum([offer_ok, resume_ok, address_ok])
            if total_filled == 0:   return "empty"
            if total_filled < 5:    return "partial"
            return "complete"

    elif step == 6:
        statuses = [get_section_status(i) for i in range(1, 6)]
        if all(s == "complete" for s in statuses): return "complete"
        if any(s != "empty"    for s in statuses): return "partial"
        return "empty"

    return "empty"


def calculate_completion():
    done = sum(1 for i in range(1, 6) if get_section_status(i) == "complete")
    return int((done / 5) * 100)


# ================= HEADER =================

st.title("Domestic Higher Education")

st.markdown("""
<style>

/* Upload box */
[data-testid="stFileUploader"] section {
    border: 1px solid #e5e7eb !important;
    border-radius: 12px !important;
    background: #ffffff !important;
    padding: 14px !important;
    transition: 0.2s ease;
}

/* Hover effect */
[data-testid="stFileUploader"] section:hover {
    border-color: #cbd5e1 !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
}

/* Hide default Streamlit text */
[data-testid="stFileUploaderDropzoneInstructions"] div {
    visibility: hidden;
}

/* Professional helper text */
[data-testid="stFileUploaderDropzoneInstructions"]::after {
    content: "Maximum file size: 5 MB";
    visibility: visible;
    display: block;
    color: #6b7280;
    font-size: 14px;
    font-weight: 400;
    margin-top: -12px;
    text-align: center;
}

/* Browse button */
[data-testid="stFileUploader"] button {
    border-radius: 10px !important;
    font-weight: 500 !important;
}

</style>
""", unsafe_allow_html=True)

steps = ["Basic Info", "Education", "Semester", "Internship", "Placement", "Review"]

# ================= NAVIGATION BAR =================

cols = st.columns(6)
for i in range(1, 7):
    status = get_section_status(i)
    color  = {"complete": "#28a745", "partial": "#ffc107"}.get(status, "#dc3545")
    if cols[i-1].button(steps[i-1]):
        st.session_state.step = i
        st.rerun()
    cols[i-1].markdown(
        f"<div style='height:5px;background:{color};border-radius:3px'></div>",
        unsafe_allow_html=True
    )

# ================= STEP 1: Basic Info =================

if st.session_state.step == 1:

    app_id = st.text_input(
        "Application ID",
        value=st.session_state.student_data.get("Application_ID", "")
    )

    tranche_number = st.selectbox(
         "Tranche Number",
         [str(i) for i in range(1, 11)],
         index=(
             int(st.session_state.student_data.get("TrancheNumber", "1")) - 1
              if str(st.session_state.student_data.get("TrancheNumber", "1")).isdigit()
              else 0
         )
    )

    current_tranche = st.session_state.student_data.get("TrancheNumber", "")
    current_app = st.session_state.student_data.get("Application_ID", "")

    # Only reset if the SAME app id changed tranche after being loaded
    if current_app == app_id and current_tranche and current_tranche != tranche_number:
        reset_student_data(app_id, tranche_number)
        st.session_state.existing_row_index = None
        st.session_state.drive_folder_id = None
        st.session_state.saved_links = {}
        st.session_state.file_store = {}
        st.session_state.fetch_app_id = ""
        st.session_state.fetch_tranche = ""
        st.session_state.data_fetched = False
        st.session_state.allow_next = False
        st.warning("⚠️ Tranche changed.\n\nPlease click Fetch Data.")
        st.rerun()

    if st.button("Fetch Data"):
        if not app_id:
            st.error("Please enter an Application ID")
        else:
            # Always check BOTH tabs
            row_idx, row_data, header_row = fetch_existing_submission(
                app_id,
                tranche_number
            )

            if row_idx is not None:
                # ── Existing submission found ──────────────────────────────
                st.success(
                    f"✅ Existing Entry Found (Tranche {tranche_number})\n\n"
                    "The existing application will be opened for editing."
                )

                st.session_state.data_fetched = True
                st.session_state.fetch_app_id = app_id
                st.session_state.fetch_tranche = tranche_number

                prev_student_data, prev_saved_links = parse_existing_row(row_data, header_row)

                # Merge fresh HED data on top (Name/Mobile/Email/Loan etc.)
                prev_student_data["TrancheNumber"] = tranche_number

                st.session_state.student_data        = prev_student_data
                st.session_state.saved_links         = prev_saved_links
                st.session_state.existing_row_index  = row_idx

                # ── FIX: Lock Drive folder ID at fetch time ───────────────
                # This prevents any rerun between fetch and submit from
                # losing the folder link and accidentally creating a new one.
                folder_id = get_folder_id_from_link(
                    prev_saved_links.get("folder_link", "")
                )
                st.session_state.drive_folder_id = folder_id  # may be None if link missing

                # Semester count
                sem_count = len(prev_student_data.get("ug_semester_data", []))
                if sem_count > 0:
                    st.session_state.semester_count = sem_count

                # Clear stale files from any previous session
                st.session_state.file_store = {}
                st.session_state.last_submit_success = None
                st.session_state.allow_next = True

                if folder_id:
                    st.success("✅ Your previously saved application has been loaded successfully.")
                else:
                    st.warning("⚠️ Drive folder link missing in sheet — will create new folder on submit")

            else:
                # ── New entry ────────────────────────────────────────────
                st.info(
                    f"🆕 New Entry (Tranche {tranche_number})\n\n"
                    "A new Google Sheet row and a new Drive folder will be created."
                )
                reset_student_data(app_id, tranche_number)
                st.session_state.data_fetched = True
                st.session_state.fetch_app_id = app_id
                st.session_state.fetch_tranche = tranche_number
                st.session_state.allow_next = True

    if st.session_state.existing_row_index is not None:
        st.info("📝 Edit Mode: You are updating an existing application.")


    name                = st.text_input("Name",                st.session_state.student_data.get("Name", ""))
    mobile              = st.text_input("Mobile",              st.session_state.student_data.get("Mobile", ""))
    email               = st.text_input("Email",               st.session_state.student_data.get("Email", ""))
    sanction_loan_amount = st.text_input("Sanction Loan Amount", st.session_state.student_data.get("SanctionLoanAmount", ""))
    disbursement_tranche_amount = st.text_input("Disbursement / Tranche Amount", st.session_state.student_data.get("DisbursementTrancheAmount", ""))
    course_name         = st.text_input("Course Name",         st.session_state.student_data.get("CourseName", ""))
    current_loan_status = st.text_input("Current Loan Status", st.session_state.student_data.get("CurrentLoanStatus", ""))

    st.session_state.student_data.update({
        "Application_ID":    app_id,
        "Name":              name,
        "Mobile":            mobile,
        "Email":             email,
        "CourseName":        course_name,
        "CurrentLoanStatus": current_loan_status,
        "TrancheNumber": tranche_number,
        "SanctionLoanAmount": sanction_loan_amount,
        "DisbursementTrancheAmount": disbursement_tranche_amount,
    })

# ================= STEP 2: Education =================

elif st.session_state.step == 2:
    saved = st.session_state.saved_links

    # ── 10th ──────────────────────────────────────────────────────────────
    st.subheader("10th Details")
    school_10 = st.text_input("School Name (10th)", value=st.session_state.student_data.get("school_10", ""))
    board_10  = st.text_input("Board (10th)",       value=st.session_state.student_data.get("board_10", ""))

    state_10 = st.selectbox("State (10th)", states_list,
        index=states_list.index(st.session_state.student_data.get("state_10", "Select State"))
              if st.session_state.student_data.get("state_10") in states_list else 0)

    year_10_val = st.session_state.student_data.get("year_10", "Select Year")
    year_10 = st.selectbox("Year of Passing (10th)", year_options,
        index=year_options.index(year_10_val) if year_10_val in year_options else 0)

    marks_type_10 = st.selectbox("Marks Type (10th)", marks_type_options,
        index=marks_type_options.index(st.session_state.student_data.get("marks_type_10", "Select"))
              if st.session_state.student_data.get("marks_type_10") in marks_type_options else 0)

    marks_10 = st.text_input("Percentage / Marks (10th)", value=st.session_state.student_data.get("marks_10", ""))

    # FIX: Show status FIRST, then uploader. persist_file called right after uploader.
    file_status_display("doc_10", saved.get("doc_10"), "10th Marksheet")
    _f = validate_file(st.file_uploader("Upload 10th Marksheet", key="doc_10"))
    persist_file("doc_10", _f)

    # ── 12th ──────────────────────────────────────────────────────────────
    st.subheader("12th Details")
    school_12 = st.text_input("School Name (12th)", value=st.session_state.student_data.get("school_12", ""))
    board_12  = st.text_input("Board (12th)",       value=st.session_state.student_data.get("board_12", ""))

    state_12 = st.selectbox("State (12th)", states_list,
        index=states_list.index(st.session_state.student_data.get("state_12", "Select State"))
              if st.session_state.student_data.get("state_12") in states_list else 0)

    year_12_val = st.session_state.student_data.get("year_12", "Select Year")
    year_12 = st.selectbox("Year of Passing (12th)", year_options,
        index=year_options.index(year_12_val) if year_12_val in year_options else 0)

    marks_type_12 = st.selectbox("Marks Type (12th)", marks_type_options,
        index=marks_type_options.index(st.session_state.student_data.get("marks_type_12", "Select"))
              if st.session_state.student_data.get("marks_type_12") in marks_type_options else 0)

    marks_12 = st.text_input("Percentage / Marks (12th)", value=st.session_state.student_data.get("marks_12", ""))

    file_status_display("doc_12", saved.get("doc_12"), "12th Marksheet")
    _f = validate_file(st.file_uploader("Upload 12th Marksheet", key="doc_12"))
    persist_file("doc_12", _f)

    # ── Graduation ────────────────────────────────────────────────────────
    st.subheader("Graduation Details")

    has_graduation = st.selectbox(
        "Do you have Graduation?",
        ["No", "Yes"],
        index=1 if st.session_state.student_data.get("HasGraduation","No") == "Yes" else 0
    )
    st.session_state.student_data["HasGraduation"] = has_graduation
    college_grad = ""
    university_grad = ""
    state_grad = ""
    year_grad = ""
    marks_type_grad = ""
    marks_grad = ""

    if has_graduation == "Yes":
       college_grad    = st.text_input("Graduation College", value=st.session_state.student_data.get("college_grad", ""))
       university_grad = st.text_input("University Name",    value=st.session_state.student_data.get("university_grad", ""))

       year_grad_val = st.session_state.student_data.get("year_grad", "Select Year")
       year_grad = st.selectbox("Year of Passing (Graduation)", year_options,
           index=year_options.index(year_grad_val) if year_grad_val in year_options else 0)

       marks_type_grad = st.selectbox("Marks Type (Graduation)", marks_type_options,
           index=marks_type_options.index(st.session_state.student_data.get("marks_type_grad", "Select"))
              if st.session_state.student_data.get("marks_type_grad") in marks_type_options else 0)

       state_grad = st.selectbox("State (Graduation)", states_list,
           index=states_list.index(st.session_state.student_data.get("state_grad", "Select State"))
              if st.session_state.student_data.get("state_grad") in states_list else 0)

       marks_grad = st.text_input("Final Percentage / CGPA", value=st.session_state.student_data.get("marks_grad", ""))

       file_status_display("doc_grad", saved.get("doc_grad"), "Graduation Marksheet")
       _f = validate_file(st.file_uploader("Upload Graduation Marksheet", key="doc_grad"))
       persist_file("doc_grad", _f)

    # ================= POST GRADUATION =================

    st.subheader("Post Graduation Details")
    
    has_pg = st.selectbox(
    "Do you have Post Graduation?",
    ["No", "Yes"],
    index=1 if st.session_state.student_data.get("HasPostGraduation") == "Yes" else 0
)

    st.session_state.student_data["HasPostGraduation"] = has_pg
    
    # Default values (to avoid NameError when PG = No)
    pg_college = ""
    pg_university = ""
    pg_state = ""
    pg_year = ""
    pg_marks_type = ""
    pg_marks = ""

    if has_pg == "Yes":

     pg_college = st.text_input(
        "PG College",
        value=st.session_state.student_data.get("pg_college", "")
    )

     pg_university = st.text_input(
        "PG University",
        value=st.session_state.student_data.get("pg_university", "")
    )

     pg_state = st.selectbox(
        "PG State",
        states_list,
        index=states_list.index(
            st.session_state.student_data.get(
                "pg_state",
                "Select State"
            )
        )
        if st.session_state.student_data.get(
            "pg_state"
        ) in states_list
        else 0
    )

     pg_year = st.selectbox(
        "PG Passing Year",
        year_options,
        index=year_options.index(
            st.session_state.student_data.get(
                "pg_year",
                "Select Year"
            )
        )
        if st.session_state.student_data.get(
            "pg_year"
        ) in year_options
        else 0
    )

     pg_marks_type = st.selectbox(
        "PG Marks Type",
        marks_type_options,
        index=marks_type_options.index(
            st.session_state.student_data.get(
                "pg_marks_type",
                "Select"
            )
        )
        if st.session_state.student_data.get(
            "pg_marks_type"
        ) in marks_type_options
        else 0
    )

     pg_marks = st.text_input(
        "PG Marks",
        value=st.session_state.student_data.get(
            "pg_marks",
            ""
        )
    )

     file_status_display(
        "doc_pg",
        saved.get("doc_pg"),
        "PG Marksheet"
    )

     _f = validate_file(
        st.file_uploader(
            "Upload PG Marksheet",
            key="doc_pg"
        )
    )

     persist_file(
        "doc_pg",
        _f
    )

    st.session_state.student_data.update({

        "pg_college": pg_college,
        "pg_university": pg_university,
        "pg_state": pg_state,
        "pg_year": pg_year,
        "pg_marks_type": pg_marks_type,
        "pg_marks": pg_marks,

    })

    # ================= OTHER COURSE =================

    st.subheader("Other Course (Optional)")
    has_other_course = st.selectbox(
        "Do you have any Other Course?",
         ["No", "Yes"],
         index=1 if st.session_state.student_data.get("HasOtherCourse") == "Yes" else 0
    )
    st.session_state.student_data["HasOtherCourse"] = has_other_course

    other_course_name = ""
    other_institute_name = ""
    other_course_completion_year = ""
    other_course_marks = ""

    if has_other_course == "Yes":
       
       other_course_name = st.text_input(
           "Course Name",
           value=st.session_state.student_data.get(
               "other_course_name",
                ""
              )
       )

       other_institute_name = st.text_input(
           "Institute Name",
           value=st.session_state.student_data.get(
               "other_institute_name",
                ""
              )
       )

       other_course_completion_year = st.selectbox(
           "Completion Year",
           year_options,
           index=year_options.index(
               st.session_state.student_data.get(
                   "other_course_completion_year",
                   "Select Year"
               )
           )

           if st.session_state.student_data.get(
               "other_course_completion_year"
               ) in year_options
               else 0
       )

       other_course_marks = st.text_input(
           "Marks / Grade",
           value=st.session_state.student_data.get(
                "other_course_marks",
                ""
              )
       )

       file_status_display(
           "other_course_doc",
           saved.get("other_course_doc"),
           "Other Course Certificate"
       )

       _f = validate_file(
           st.file_uploader(
               "Upload Other Course Certificate",
               key="other_course_doc"
              )
       )

       persist_file(
           "other_course_doc",
           _f
       )

    st.session_state.student_data.update({

    "other_course_name": other_course_name,
    "other_institute_name": other_institute_name,
    "other_course_completion_year": other_course_completion_year,
    "other_course_marks": other_course_marks,

})

    # ── Competitive Exam ──────────────────────────────────────────────────
    st.subheader("Competitive Exam Details")
    has_exam = st.selectbox(
        "Have you appeared for any Competitive Exam?",
        ["No", "Yes"],
        index=1 if st.session_state.student_data.get("HasCompetitiveExam","No") == "Yes" else 0
    )
    st.session_state.student_data["HasCompetitiveExam"] = has_exam

    exam_name = ""
    exam_year = ""
    exam_score = ""
    exam_rank = ""

    if has_exam == "Yes":
      exam_name = st.text_input("Exam Name", value=st.session_state.student_data.get("exam_name", ""))

      exam_year_val = st.session_state.student_data.get("exam_year", "Select Year")
      exam_year = st.selectbox("Exam Year", year_options,
        index=year_options.index(exam_year_val) if exam_year_val in year_options else 0)

      exam_score = st.text_input("Score", value=st.session_state.student_data.get("exam_score", ""))
      exam_rank  = st.text_input("Rank",  value=st.session_state.student_data.get("exam_rank", ""))

      file_status_display("exam_doc", saved.get("exam_doc"), "Exam Scorecard")
      _f = validate_file(st.file_uploader("Upload Scorecard", key="exam_doc"))
      persist_file("exam_doc", _f)

    st.session_state.student_data.update({
        "school_10": school_10, "board_10": board_10, "state_10": state_10,
        "year_10": year_10, "marks_type_10": marks_type_10, "marks_10": marks_10,
        "school_12": school_12, "board_12": board_12, "state_12": state_12,
        "year_12": year_12, "marks_type_12": marks_type_12, "marks_12": marks_12,
        "college_grad": college_grad, "university_grad": university_grad, "state_grad": state_grad,
        "year_grad": year_grad, "marks_type_grad": marks_type_grad, "marks_grad": marks_grad,
        "HasCompetitiveExam": has_exam,
        "exam_name": exam_name, "exam_year": exam_year, "exam_score": exam_score, "exam_rank": exam_rank,
        "HasGraduation": has_graduation,
        "HasPostGraduation": has_pg,

        "pg_college": pg_college,
        "pg_university": pg_university,
        "pg_state": pg_state,
        "pg_year": pg_year,
        "pg_marks_type": pg_marks_type,
        "pg_marks": pg_marks,

        "HasOtherCourse": has_other_course,
        "other_course_name": other_course_name,
        "other_institute_name": other_institute_name,
        "other_course_completion_year": other_course_completion_year,
        "other_course_marks": other_course_marks,
    })

# ================= STEP 3: Semesters =================

elif st.session_state.step == 3:
    saved = st.session_state.saved_links
    st.subheader("Course Progression - Semester Wise")
    st.markdown("### 🎓 Under Graduation Semester Details")

    semester_data    = st.session_state.student_data.get("ug_semester_data", [])
    updated_semesters = []
# ================= PG SEMESTER INIT =================

    pg_semester_data = st.session_state.student_data.get(
    "pg_semester_data",
    []
)

    updated_pg_semesters = []

    has_pg = st.session_state.student_data.get(
    "HasPostGraduation",
    "No"
)

    for i in range(1, st.session_state.semester_count + 1):
        st.markdown(f"### UG Semester {i}")
        existing = semester_data[i-1] if len(semester_data) >= i else {}

        college_name   = st.text_input(f"UG College (Semester {i})", value=existing.get("college", ""),    key=f"sem_college_{i}")
        course_name_s  = st.text_input(f"UG Course (Semester {i})",  value=existing.get("course", ""),     key=f"sem_course_{i}")

        year_sem = st.selectbox(f"UG Year (Semester {i})", year_options,
            index=year_options.index(existing.get("year", "Select Year")) if existing.get("year") in year_options else 0,
            key=f"sem_year_{i}")

        marks_type_sem = st.selectbox(f"UG Marks Type (Semester {i})", marks_type_options,
            index=marks_type_options.index(existing.get("marks_type", "Select")) if existing.get("marks_type") in marks_type_options else 0,
            key=f"sem_marks_type_{i}")

        sem_marks = st.text_input(f"UG Marks (Semester {i})", value=existing.get("marks", ""), key=f"sem_marks_{i}")

        state_sem = st.selectbox(f"UG State (Semester {i})", states_list,
            index=states_list.index(existing.get("state", "Select State")) if existing.get("state") in states_list else 0,
            key=f"sem_state_{i}")

        sem_key = f"UG_Semester_{i}"
        file_status_display(sem_key, saved.get(sem_key), f"UG Semester {i} Marksheet")
        _f = validate_file(st.file_uploader(f"UG Semester {i} Marksheet", key=f"sem_doc_{i}"))
        persist_file(sem_key, _f)

        updated_semesters.append({
            "sem_no":     i,
            "college":    college_name,
            "course":     course_name_s,
            "year":       year_sem,
            "marks_type": marks_type_sem,
            "marks":      sem_marks,
            "state":      state_sem,
            "doc":        None
        })

    st.session_state.student_data["ug_semester_data"] = updated_semesters
# ================= PG SEMESTERS =================

    if has_pg == "Yes":

      st.markdown("---")
      st.subheader("Post Graduation Semester Details")

      for i in range(1, st.session_state.semester_count + 1):

        st.markdown(f"### PG Semester {i}")

        existing = (
            pg_semester_data[i-1]
            if len(pg_semester_data) >= i
            else {}
        )

        college_name = st.text_input(
            f"PG College (Semester {i})",
            value=existing.get("college", ""),
            key=f"pg_sem_college_{i}"
        )

        course_name = st.text_input(
            f"PG Course (Semester {i})",
            value=existing.get("course", ""),
            key=f"pg_sem_course_{i}"
        )

        year = st.selectbox(
            f"PG Year (Semester {i})",
            year_options,
            index=year_options.index(
                existing.get(
                    "year",
                    "Select Year"
                )
            )
            if existing.get("year") in year_options
            else 0,
            key=f"pg_sem_year_{i}"
        )

        marks_type = st.selectbox(
            f"PG Marks Type (Semester {i})",
            marks_type_options,
            index=marks_type_options.index(
                existing.get("marks_type", "Select")
            )
            if existing.get("marks_type") in marks_type_options
            else 0,
            key=f"pg_sem_marks_type_{i}"
        )

        marks = st.text_input(
            f"PG Marks (Semester {i})",
            value=existing.get("marks", ""),
            key=f"pg_sem_marks_{i}"
        )

        state = st.selectbox(
            f"PG State (Semester {i})",
            states_list,
            index=states_list.index(
                existing.get("state", "Select State")
            )
            if existing.get("state") in states_list
            else 0,
            key=f"pg_sem_state_{i}"
        )

        pg_doc_key = f"PG_Semester_{i}"

        file_status_display(
            pg_doc_key,
            saved.get(pg_doc_key),
            f"PG Semester {i} Marksheet"
        )

        _f = validate_file(
            st.file_uploader(
                f"Upload PG Semester {i} Marksheet",
                key=f"pg_sem_doc_{i}"
            )
        )

        persist_file(
            pg_doc_key,
            _f
        )

        updated_pg_semesters.append({

            "sem_no": i,

            "college": college_name,

            "course": course_name,

            "year": year,

            "marks_type": marks_type,

            "marks": marks,

            "state": state

        })

    st.session_state.student_data["pg_semester_data"] = updated_pg_semesters

    colA, colB = st.columns(2)
    with colA:
        if st.button("➕ Add Semester") and st.session_state.semester_count < 8:
            st.session_state.semester_count += 1
            st.rerun()
    with colB:
        if st.button("➖ Remove Semester") and st.session_state.semester_count > 1:
            st.session_state.semester_count -= 1
            st.rerun()

# ================= STEP 4: Internship =================

elif st.session_state.step == 4:
    saved = st.session_state.saved_links
    st.subheader("Internship Details")

    intern_company  = st.text_input("Internship Company", value=st.session_state.student_data.get("intern_company", ""))
    intern_role     = st.text_input("Role",               value=st.session_state.student_data.get("intern_role", ""))
    intern_duration = st.text_input("Duration",           value=st.session_state.student_data.get("intern_duration", ""))

    intern_state = st.selectbox("Internship State", states_list,
        index=states_list.index(st.session_state.student_data.get("intern_state", "Select State"))
              if st.session_state.student_data.get("intern_state") in states_list else 0)

    file_status_display("intern_doc", saved.get("intern_doc"), "Internship Certificate")
    _f = validate_file(st.file_uploader("Internship Certificate", key="intern_doc"))
    persist_file("intern_doc", _f)

    st.session_state.student_data.update({
        "intern_company":  intern_company,
        "intern_role":     intern_role,
        "intern_duration": intern_duration,
        "intern_state":    intern_state,
    })

# ================= STEP 5: Placement =================

elif st.session_state.step == 5:
    saved = st.session_state.saved_links
    st.subheader("Placement Details")

    placed_val = st.session_state.student_data.get("Placed", "No")
    placed = st.selectbox("Placed?", ["No", "Yes"],
        index=["No", "Yes"].index(placed_val) if placed_val in ["No", "Yes"] else 0)
    st.session_state.student_data["Placed"] = placed

    if placed == "Yes":
        company         = st.text_input("Company",              value=st.session_state.student_data.get("company", ""))
        role            = st.text_input("Role",                 value=st.session_state.student_data.get("role", ""))
        ctc             = st.text_input("CTC (Annual Package)", value=st.session_state.student_data.get("ctc", ""))
        current_address = st.text_area("Current Address",       value=st.session_state.student_data.get("current_address", ""))

        country = st.selectbox("Country of Job", country_list,
            index=country_list.index(st.session_state.student_data.get("country", "Select Country"))
                  if st.session_state.student_data.get("country") in country_list else 0)

        file_status_display("offer_doc",   saved.get("offer_doc"),   "Offer Letter")
        _f = validate_file(st.file_uploader("Offer Letter",   key="offer_doc"))
        persist_file("offer_doc", _f)

        file_status_display("address_doc", saved.get("address_doc"), "Address Proof")
        _f = validate_file(st.file_uploader("Address Proof",  key="address_doc"))
        persist_file("address_doc", _f)

        file_status_display("resume_doc",  saved.get("resume_doc"),  "Resume")
        _f = validate_file(st.file_uploader("Upload Resume",  key="resume_doc"))
        persist_file("resume_doc", _f)

        st.session_state.student_data.update({
            "company": company, "role": role, "ctc": ctc,
            "current_address": current_address, "country": country,
        })

# ================= STEP 6: Review & Submit =================
elif st.session_state.step == 6:

    st.subheader("📋 Complete Application Review")

    data = st.session_state.student_data
    saved = st.session_state.saved_links
    fs = st.session_state.file_store

    if st.session_state.existing_row_index is not None:
        st.info("📝 Edit Mode : Existing application will be updated.")

    # =========================================================
    # BASIC
    # =========================================================

    st.markdown("## 🧾 Basic Information")

    c1, c2 = st.columns(2)

    with c1:
        st.write("**Application ID**")
        st.write(data.get("Application_ID", ""))

        st.write("**Name**")
        st.write(data.get("Name", ""))

        st.write("**Mobile**")
        st.write(data.get("Mobile", ""))

        st.write("**Email**")
        st.write(data.get("Email", ""))

    with c2:

        st.write("**Course**")
        st.write(data.get("CourseName", ""))

        st.write("**Current Loan Status**")
        st.write(data.get("CurrentLoanStatus", ""))

        st.write("**Tranche Number**")
        st.write(data.get("TrancheNumber", ""))

        st.write("**Sanction Amount**")
        st.write(data.get("SanctionLoanAmount", ""))

        st.write("**Disbursement Amount**")
        st.write(data.get("DisbursementTrancheAmount", ""))

    st.divider()

    # =========================================================
    # EDUCATION
    # =========================================================

    st.markdown("## 🎓 Education")

    st.markdown("### 10th")

    st.write("School :", data.get("school_10",""))
    st.write("Board :", data.get("board_10",""))
    st.write("State :", data.get("state_10",""))
    st.write("Year :", data.get("year_10",""))
    st.write("Marks :", data.get("marks_10",""))
    st.write("Marks Type :",data.get("marks_type_10",""))

    if fs.get("doc_10"):
        st.success(f"✅ {fs['doc_10']['name']}")
    elif saved.get("doc_10"):
        st.markdown(f"📄 [View Document]({saved['doc_10']})")
    else:
        st.warning("10th Marksheet Missing")

    st.divider()

    st.markdown("### 12th")

    st.write("School :", data.get("school_12",""))
    st.write("Board :", data.get("board_12",""))
    st.write("State :", data.get("state_12",""))
    st.write("Year :", data.get("year_12",""))
    st.write("Marks :", data.get("marks_12",""))
    st.write("Marks Type :",data.get("marks_type_12",""))

    if fs.get("doc_12"):
        st.success(f"✅ {fs['doc_12']['name']}")
    elif saved.get("doc_12"):
        st.markdown(f"📄 [View Document]({saved['doc_12']})")
    else:
        st.warning("12th Marksheet Missing")

    st.divider()

    if data.get("HasGraduation") == "Yes":
       st.markdown("### Graduation")

       st.write("College :", data.get("college_grad",""))
       st.write("University :", data.get("university_grad",""))
       st.write("State :", data.get("state_grad",""))
       st.write("Year :", data.get("year_grad",""))
       st.write("Marks :", data.get("marks_grad",""))
       st.write("Marks Type :", data.get("marks_type_grad",""))

       if fs.get("doc_grad"):
           st.success(f"✅ {fs['doc_grad']['name']}")
       elif saved.get("doc_grad"):
           st.markdown(f"📄 [View Document]({saved['doc_grad']})")
       else:
           st.warning("Graduation Marksheet Missing")

           st.divider()
           
    if data.get("HasPostGraduation") == "Yes":

        st.divider()

        st.markdown("### Post Graduation")

        st.write("College :", data.get("pg_college",""))
        st.write("University :", data.get("pg_university",""))
        st.write("State :", data.get("pg_state",""))
        st.write("Year :", data.get("pg_year",""))
        st.write("Marks :", data.get("pg_marks",""))
        st.write("Marks Type :", data.get("pg_marks_type",""))

        if fs.get("doc_pg"):
            st.success(f"✅ {fs['doc_pg']['name']}")
        elif saved.get("doc_pg"):
            st.markdown(f"📄 [View Document]({saved['doc_pg']})")
        else:
            st.warning("PG Marksheet Missing")

        st.divider()

    if data.get("HasOtherCourse") == "Yes":
       st.markdown("### Other Course")

       st.write("Course :", data.get("other_course_name",""))
       st.write("Institute :", data.get("other_institute_name",""))
       st.write("Completion Year :", data.get("other_course_completion_year",""))
       st.write("Marks :", data.get("other_course_marks",""))

       if fs.get("other_course_doc"):
           st.success(f"✅ {fs['other_course_doc']['name']}")
       elif saved.get("other_course_doc"):
           st.markdown(f"📄 [View Certificate]({saved['other_course_doc']})")
       else:
           st.warning("Certificate Missing")

       st.divider()

    if data.get("HasCompetitiveExam") == "Yes":
       st.markdown("### Competitive Exam")

       st.write("Exam :", data.get("exam_name",""))
       st.write("Year :", data.get("exam_year",""))
       st.write("Score :", data.get("exam_score",""))
       st.write("Rank :", data.get("exam_rank",""))

       if fs.get("exam_doc"):
          st.success(f"✅ {fs['exam_doc']['name']}")
       elif saved.get("exam_doc"):
          st.markdown(f"📄 [View Score Card]({saved['exam_doc']})")
       else:
          st.warning("Score Card Missing")

       st.divider()

    # =========================================================
    # UG SEMESTERS
    # =========================================================

    st.markdown("## 📚 UG Semester Details")

    for sem in data.get("ug_semester_data", []):

        sem_no = sem.get("sem_no")

        st.markdown(f"### UG Semester {sem_no}")

        st.write("College :", sem.get("college",""))
        st.write("Course :", sem.get("course",""))
        st.write("Year :", sem.get("year",""))
        st.write("Marks :", sem.get("marks",""))
        st.write("State :", sem.get("state",""))
        st.write("Marks Type :", sem.get("marks_type",""))

        key = f"UG_Semester_{sem_no}"

        if fs.get(key):
            st.success(f"✅ {fs[key]['name']}")
        elif saved.get(key):
            st.markdown(f"📄 [View Document]({saved[key]})")
        else:
            st.warning("Document Missing")

        # =========================================================
    # PG SEMESTERS
    # =========================================================

    if data.get("HasPostGraduation") == "Yes":

        st.divider()
        st.markdown("## 🎓 PG Semester Details")

        for sem in data.get("pg_semester_data", []):

            sem_no = sem.get("sem_no")

            st.markdown(f"### PG Semester {sem_no}")

            st.write("College :", sem.get("college", ""))
            st.write("Course :", sem.get("course", ""))
            st.write("Year :", sem.get("year", ""))
            st.write("Marks :", sem.get("marks", ""))
            st.write("State :", sem.get("state",""))
            st.write("Marks Type :", sem.get("marks_type", ""))

            key = f"PG_Semester_{sem_no}"

            if fs.get(key):
                st.success(f"✅ {fs[key]['name']}")
            elif saved.get(key):
                st.markdown(f"📄 [View Document]({saved[key]})")
            else:
                st.warning("Document Missing")

    st.divider()

    # =========================================================
    # INTERNSHIP
    # =========================================================

    st.markdown("## 💼 Internship")

    st.write("Company :", data.get("intern_company", ""))
    st.write("Role :", data.get("intern_role", ""))
    st.write("Duration :", data.get("intern_duration", ""))
    st.write("State :", data.get("intern_state", ""))

    if fs.get("intern_doc"):
        st.success(f"✅ {fs['intern_doc']['name']}")
    elif saved.get("intern_doc"):
        st.markdown(f"📄 [View Internship Certificate]({saved['intern_doc']})")
    else:
        st.warning("Internship Certificate Missing")

    st.divider()

    # =========================================================
    # PLACEMENT
    # =========================================================

    st.markdown("## 🏢 Placement")

    st.write("Placed :", data.get("Placed", ""))

    if data.get("Placed") == "Yes":

        st.write("Company :", data.get("company", ""))
        st.write("Role :", data.get("role", ""))
        st.write("CTC :", data.get("ctc", ""))
        st.write("Current Address :", data.get("current_address", ""))
        st.write("Country :", data.get("country", ""))

        docs = [
            ("offer_doc", "Offer Letter"),
            ("address_doc", "Address Proof"),
            ("resume_doc", "Resume"),
        ]

        for key, label in docs:

            if fs.get(key):
                st.success(f"✅ {label}: {fs[key]['name']}")
            elif saved.get(key):
                st.markdown(f"📄 {label}: [View Document]({saved[key]})")
            else:
                st.warning(f"{label} Missing")

    st.divider()

    # =========================================================
    # SUBMISSION STATUS
    # =========================================================

    if st.session_state.get("last_submit_success"):
        st.success(st.session_state.last_submit_success)

    # ================= FINAL SUBMIT BUTTON =================        

    if st.button("✅ Final Submit"):
        current_app = data.get("Application_ID", "")
        current_tranche = data.get("TrancheNumber", "")

        # User changed App ID / Tranche but didn't fetch again
        if (
            st.session_state.fetch_app_id != current_app
            or
            st.session_state.fetch_tranche != current_tranche
            ):
            st.error(
                "⚠️ Application ID or Tranche Number has changed.\n\n"
                "Please click 'Fetch Data' before Final Submit."
            )
            st.stop()
        ensure_sheet_headers()
        invalid_files = validate_all_uploaded_files()
        if invalid_files:
            file_names = []
            for _, name, size in invalid_files:
                file_names.append(
                    f"• {name} ({size} MB)"
                )
            st.error(
                "❌ Application Submission Failed"
            )
            st.error(
                "The following document(s) "
                "exceed the maximum allowed "
                "file size of 5MB:"
            )
            st.markdown(
                "\n".join(file_names)
            )
            st.warning(
                "Please upload files smaller "
                "than 5MB and try again."
            )

            st.stop()

        try:
            # Step 0: Ensure sheet has all required header columns (fixes old sheets)
            ensure_sheet_headers()

            # Step 1: Get folder (never creates duplicate for existing apps)
            folder_id = resolve_or_create_folder(data)

            if not folder_id:
                raise Exception("Drive folder could not be resolved. Contact admin.")

            # Folder link for sheet
            if st.session_state.existing_row_index is not None:
                # Keep exact old link from sheet
                folder_link = st.session_state.saved_links.get("folder_link", "")
                if not folder_link:
                    folder_link = f"https://drive.google.com/drive/folders/{folder_id}"
            else:
                folder_link = f"https://drive.google.com/drive/folders/{folder_id}"

            # Step 2: Start uploaded_links from ALL previously saved links
            # (preserves every doc already in Drive — only NEW uploads overwrite)
            uploaded_links = {
                k: v for k, v in st.session_state.saved_links.items()
                if k != "folder_link" and v
            }

            # Step 3: Upload only NEW files from file_store
            all_doc_keys = [
                "doc_10",
                "doc_12",
                "doc_grad",
                "doc_pg",
                "other_course_doc",
                "exam_doc",
                "intern_doc",
                "offer_doc",
                "address_doc",
                "resume_doc",

                "UG_Semester_1",
                "UG_Semester_2",
                "UG_Semester_3",
                "UG_Semester_4",
                "UG_Semester_5",
                "UG_Semester_6",
                "UG_Semester_7",
                "UG_Semester_8",

                "PG_Semester_1",
                "PG_Semester_2",
                "PG_Semester_3",
                "PG_Semester_4",
                "PG_Semester_5",
                "PG_Semester_6",
                "PG_Semester_7",
                "PG_Semester_8",
]
            doc_name_mapping = {
                "doc_10": "10th Doc",
                "doc_12": "12th Doc",
                "doc_grad": "Graduation Doc",
                "doc_pg": "Post Graduation Doc",
                "other_course_doc": "Other Course Certificate",
                "exam_doc": "Exam Doc",
                "intern_doc": "Intern Doc",
                "offer_doc": "Offer Letter",
                "address_doc": "Address Proof",
                "resume_doc": "Resume",
                "UG_Semester_1": "UG Semester 1",
                "UG_Semester_2": "UG Semester 2",
                "UG_Semester_3": "UG Semester 3",
                "UG_Semester_4": "UG Semester 4",
                "UG_Semester_5": "UG Semester 5",
                "UG_Semester_6": "UG Semester 6",
                "UG_Semester_7": "UG Semester 7",
                "UG_Semester_8": "UG Semester 8",
                "PG_Semester_1": "PG Semester 1",
                "PG_Semester_2": "PG Semester 2",
                "PG_Semester_3": "PG Semester 3",
                "PG_Semester_4": "PG Semester 4",
                "PG_Semester_5": "PG Semester 5",
                "PG_Semester_6": "PG Semester 6",
                "PG_Semester_7": "PG Semester 7",
                "PG_Semester_8": "PG Semester 8"
            }
            for key in all_doc_keys:
                if key in st.session_state.file_store:
                    file_obj = get_stored_file(key)
                    if file_obj:
                        existing_link = (
                            st.session_state.saved_links.get(key)
                        )
                        ext = os.path.splitext(
                            file_obj.name
                        )[1]
                        fixed_name = (
                            doc_name_mapping.get(
                                key,
                                key
                            ) + ext
                        )

                        link = upload_file_to_drive(
                            file_obj,
                            folder_id,
                            fixed_name,
                            existing_link
                        )
                        uploaded_links[key] = link

            # Semester docs
            for sem in data.get("ug_semester_data", []):
                sem_no = sem.get("sem_no")
                sem_key = f"UG_Semester_{sem_no}"
                if sem_key in st.session_state.file_store:
                    file_obj = get_stored_file(sem_key)
                    if file_obj:
                        existing_link = (
                            st.session_state.saved_links.get(sem_key)
                        )
                        ext = os.path.splitext(
                            file_obj.name
                        )[1]
                        fixed_name = (
                            f"UG Semester{sem_no} Doc{ext}"
                        )
                        link = upload_file_to_drive(
                            file_obj,
                            folder_id,
                            fixed_name,
                            existing_link
                        )
                        uploaded_links[sem_key] = link

            # Step 4: Save or update sheet row
            row_idx, _, _ = fetch_existing_submission(
                data.get("Application_ID", ""),
                data.get("TrancheNumber", "")
            )
            if row_idx:
                update_sheet_row(
                    row_idx,
                    data,
                    folder_link,
                    uploaded_links
                )
                msg = "🎉 Application Updated Successfully!"

            else:
                save_to_sheet(
                    data,
                    folder_link,
                    uploaded_links
                )

                msg = "🎉 Application Submitted Successfully!"


            # Step 5: Update session state so next submit is correct
            st.session_state.drive_folder_id = folder_id
            st.session_state.saved_links["folder_link"] = folder_link
            st.session_state.saved_links.update(uploaded_links)

            st.session_state.fetch_app_id = data.get(
                "Application_ID",
                ""
            )

            st.session_state.fetch_tranche = data.get(
                "TrancheNumber",
                ""
            )

            st.session_state.data_fetched = True

            # If new submission, fetch the row index for future updates
            if not st.session_state.existing_row_index:
                new_row_idx, _, _ = fetch_existing_submission(
                    data.get("Application_ID", ""),
                    data.get("TrancheNumber", "")
                )
                if new_row_idx:
                    st.session_state.existing_row_index = new_row_idx

            # Clear only file_store (not saved_links) after successful save
            st.session_state.file_store = {}

            # Persist success message so it survives the rerun below
            st.session_state.last_submit_success = msg

            st.rerun()

        except Exception as e:
            st.session_state.last_submit_success = None
            st.error(f"❌ Submission Failed: {e}")

# ================= BOTTOM NAVIGATION =================

c1, c2 = st.columns(2)
if c1.button("⬅ Back") and st.session_state.step > 1:
    st.session_state.step -= 1
    st.rerun()
if c2.button("Next ➡"):
    if (
        st.session_state.step == 1
        and
        not st.session_state.allow_next
    ):
        st.error(
            "Please click Fetch Data first."
        )

    elif st.session_state.step < 6:
            st.session_state.step += 1
            st.rerun()
