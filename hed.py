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
FETCH_TAB = "HED"
SAVE_TAB = "HED_SUBMISSIONS"

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
        "semester_count": 2,
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
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session()


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

def fetch_application_data(app_id):
    """Fetch basic data from HED tab."""
    result = sheet_service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"{FETCH_TAB}!A:G"
    ).execute()
    values = result.get("values", [])
    for row in values[1:]:
        if row and row[0] == app_id:
            return {
                "Application_ID":    row[0],
                "Name":              row[1] if len(row) > 1 else "",
                "Mobile":            row[2] if len(row) > 2 else "",
                "Email":             row[3] if len(row) > 3 else "",
                "LoanAmount":        row[4] if len(row) > 4 else "",
                "CourseName":        row[5] if len(row) > 5 else "",
                "CurrentLoanStatus": row[6] if len(row) > 6 else "",
            }
    return None


def fetch_existing_submission(app_id):
    """Fetch existing row from HED_SUBMISSIONS tab. Returns (row_index, row_data, header_row)."""
    result = sheet_service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"{SAVE_TAB}!A:ZZ"
    ).execute()
    values = result.get("values", [])
    if not values:
        return None, None, None
    header_row = values[0]
    for idx, row in enumerate(values[1:], start=2):
        if row and len(row) > 0 and row[0] == app_id:
            return idx, row, header_row
    return None, None, None


def parse_existing_row(row_data, header_row):
    """
    Parse a submission row into student_data dict and saved_links dict.

    KEY: We build a header→index map first, then look up every column by
    its exact header name. This survives column reordering and the
    ensure_sheet_headers() expansion without ever reading the wrong cell.
    """
    # ── Build header→index map (case + space insensitive) ─────────────────
    hmap = {}
    for idx, h in enumerate(header_row):
        key = str(h).strip().lower()
        hmap[key] = idx

    def ph(header_name, fallback_idx=None):
        """Get row value by header name; fallback to positional index if missing."""
        idx = hmap.get(str(header_name).strip().lower())
        if idx is not None:
            return row_data[idx] if idx < len(row_data) else ""
        if fallback_idx is not None:
            return row_data[fallback_idx] if fallback_idx < len(row_data) else ""
        return ""

    def p(i):
        return row_data[i] if i < len(row_data) else ""

    student_data = {
        "Application_ID":    p(0),
        "Name":              p(1),
        "Mobile":            p(2),
        "Email":             p(3),
        "LoanAmount":        p(4),
        "CourseName":        p(5),
        "CurrentLoanStatus": p(6),

        "school_10":      ph("10th school",     7),
        "board_10":       ph("10th board",      8),
        "state_10":       ph("10th state",      9),
        "year_10":        ph("10th year",       10),
        "marks_type_10":  ph("10th marks type", 11),
        "marks_10":       ph("10th marks",      12),

        "school_12":      ph("12th school",     13),
        "board_12":       ph("12th board",      14),
        "state_12":       ph("12th state",      15),
        "year_12":        ph("12th year",       16),
        "marks_type_12":  ph("12th marks type", 17),
        "marks_12":       ph("12th marks",      18),

        "college_grad":     ph("graduation college", 19),
        "university_grad":  ph("university",         20),
        "state_grad":       ph("graduation state",   21),
        "year_grad":        ph("grad year",          22),
        "marks_type_grad":  ph("grad marks type",    23),
        "marks_grad":       ph("grad marks",         24),

        "exam_name":  ph("exam name",  25),
        "exam_year":  ph("exam year",  26),
        "exam_score": ph("exam score", 27),
        "exam_rank":  ph("exam rank",  28),

        "intern_company":  ph("Intern Company"),
        "intern_role":     ph("Intern Role"),
        "intern_duration": ph("Intern Duration"),
        "intern_state":    ph("Intern State"),

        "Placed":          ph("Placed"),
        "company":         ph("Company"),
        "role":            ph("Role"),
        "ctc":             ph("CTC"),
        "current_address": ph("Current Address"),
        "country":         ph("Country"),
    }

    # Semester data — read by sem header names first, positional fallback
    semester_data = []
    for i in range(1, 9):
        college    = ph(f"sem{i}_college")    or p(29 + (i-1)*6)
        course     = ph(f"sem{i}_course")     or p(30 + (i-1)*6)
        year       = ph(f"sem{i}_year")       or p(31 + (i-1)*6)
        marks_type = ph(f"sem{i}_marks_type") or p(32 + (i-1)*6)
        marks      = ph(f"sem{i}_marks")      or p(33 + (i-1)*6)
        state      = ph(f"sem{i}_state")      or p(34 + (i-1)*6)
        if college or marks:
            semester_data.append({
                "sem_no":     i,
                "college":    college,
                "course":     course,
                "year":       year,
                "marks_type": marks_type,
                "marks":      marks,
                "state":      state,
                "doc":        None
            })
    student_data["semester_data"] = semester_data

    # ── Read all Drive links by header name ───────────────────────────────
    # This works whether columns are at 78, 87, or any position — as long
    # as the header row has the right names (ensure_sheet_headers adds them).
    saved_links = {
        "folder_link": ph("drivefolderlink"),
        "doc_10": ph("10th Doc") or ph("doc_10"),
        "doc_12": ph("12th Doc") or ph("doc_12"),
        "doc_grad": ph("Grad Doc") or ph("doc_grad"),
        "exam_doc": ph("Exam Doc") or ph("exam_doc"),
        "Semester_1": ph("Sem1 Doc") or ph("Semester_1"),
        "Semester_2": ph("Sem2 Doc") or ph("Semester_2"),
        "Semester_3": ph("Sem3 Doc") or ph("Semester_3"),
        "Semester_4": ph("Sem4 Doc") or ph("Semester_4"),
        "Semester_5": ph("Sem5 Doc") or ph("Semester_5"),
        "Semester_6": ph("Sem6 Doc") or ph("Semester_6"),
        "Semester_7": ph("Sem7 Doc") or ph("Semester_7"),
        "Semester_8": ph("Sem8 Doc") or ph("Semester_8"),
        "intern_doc": ph("Intern Doc") or ph("intern_doc"),
        "offer_doc": ph("Offer Letter") or ph("offer_doc"),
        "address_doc": ph("Address Proof") or ph("address_doc"),
        "resume_doc": ph("Resume") or ph("resume_doc"),
    }

    saved_links = {
        k: v for k, v in saved_links.items()
        if str(v).strip()
    }

    # Store debug info for Step 1 expander
    folder_col_idx = hmap.get("drivefolderlink")
    st.session_state["_debug_headers"]        = list(header_row)
    st.session_state["_debug_folder_col_idx"] = folder_col_idx
    st.session_state["_debug_total_cols"]     = len(header_row)
    st.session_state["_debug_hmap"]           = hmap
    st.session_state["_debug_saved_links"]    = dict(saved_links)

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


def find_existing_drive_folder(app_id, name):
    """
    Search Drive for an existing folder named AppID_Name inside FOLDER_ID.
    Returns folder_id if found, else None.
    """
    try:
        folder_name = f"{app_id}_{name}"
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
    if st.session_state.drive_folder_id:
        return st.session_state.drive_folder_id

    # ── Priority 2: link in sheet ───────────────────────────────────────
    folder_link = st.session_state.saved_links.get("folder_link", "")
    folder_id   = get_folder_id_from_link(folder_link)
    if folder_id:
        st.session_state.drive_folder_id = folder_id
        return folder_id

    # ── Priority 3: search Drive by name (old submissions, link missing) ─
    if (st.session_state.get("existing_row_index") is not None or app_id):
        found_id = find_existing_drive_folder(app_id, name)
        if found_id:
            st.info(f"📁 Existing Drive folder found by name search.")
            st.session_state.drive_folder_id = found_id
            # Also update saved_links so folder link gets written to sheet on save
            st.session_state.saved_links["folder_link"] = (
                f"https://drive.google.com/drive/folders/{found_id}"
            )
            return found_id

    # ── Priority 4: create new folder ──────────────────────────────────
    folder_name   = f"{app_id}_{name}"
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
    "Application_ID","Name","Mobile","Email","LoanAmount","CourseName","CurrentLoanStatus",
    "10th School","10th Board","10th State","10th Year","10th Marks Type","10th Marks",
    "12th School","12th Board","12th State","12th Year","12th Marks Type","12th Marks",
    "Graduation College","University","Graduation State","Grad Year","Grad Marks Type","Grad Marks",
    "Exam Name","Exam Year","Exam Score","Exam Rank",
    "sem1_college","sem1_course","sem1_year","sem1_marks_type","sem1_marks","sem1_state",
    "sem2_college","sem2_course","sem2_year","sem2_marks_type","sem2_marks","sem2_state",
    "sem3_college","sem3_course","sem3_year","sem3_marks_type","sem3_marks","sem3_state",
    "sem4_college","sem4_course","sem4_year","sem4_marks_type","sem4_marks","sem4_state",
    "sem5_college","sem5_course","sem5_year","sem5_marks_type","sem5_marks","sem5_state",
    "sem6_college","sem6_course","sem6_year","sem6_marks_type","sem6_marks","sem6_state",
    "sem7_college","sem7_course","sem7_year","sem7_marks_type","sem7_marks","sem7_state",
    "sem8_college","sem8_course","sem8_year","sem8_marks_type","sem8_marks","sem8_state",
    "Intern Company","Intern Role","Intern Duration","Intern State",
    "Placed","Company","Role","CTC","Current Address","Country",
    "DriveFolderLink",
    "doc_10","doc_12","doc_grad","exam_doc",
    "Semester_1","Semester_2","Semester_3","Semester_4","Semester_5","Semester_6","Semester_7","Semester_8",
    "intern_doc","offer_doc","address_doc","resume_doc",
    "FormStatus","SubmittedAt"
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
    result = sheet_service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range=f"{SAVE_TAB}!1:1"
    ).execute()
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

    sheet_service.spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=range_notation,
        valueInputOption="RAW",
        body={"values": [missing]}
    ).execute()


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
    semesters = data_dict.get("semester_data", [])
    semester_filled = any(
        sem.get("college") and (
            st.session_state.file_store.get(f"Semester_{sem.get('sem_no')}") or
            st.session_state.saved_links.get(f"Semester_{sem.get('sem_no')}")
        )
        for sem in semesters
    )
    if not semester_filled:
        return "PARTIAL"
    if all(s == "complete" for s in statuses):
        return "COMPLETE"
    if any(s != "empty" for s in statuses):
        return "PARTIAL"
    return "EMPTY"


def build_row_values(data_dict, folder_link, uploaded_links):
    semesters = data_dict.get("semester_data", [])
    sem_values = []
    for i in range(8):
        if i < len(semesters):
            sem = semesters[i]
            sem_values.extend([
                sem.get("college", ""),
                sem.get("course", ""),
                clean_value(sem.get("year", "")),
                clean_value(sem.get("marks_type", "")),
                sem.get("marks", ""),
                clean_value(sem.get("state", ""))
            ])
        else:
            sem_values.extend(["", "", "", "", "", ""])

    form_status = calculate_form_status(data_dict)

    return [
        data_dict.get("Application_ID", ""),
        data_dict.get("Name", ""),
        data_dict.get("Mobile", ""),
        data_dict.get("Email", ""),
        data_dict.get("LoanAmount", ""),
        data_dict.get("CourseName", ""),
        data_dict.get("CurrentLoanStatus", ""),
        data_dict.get("school_10", ""),
        data_dict.get("board_10", ""),
        clean_value(data_dict.get("state_10", "")),
        clean_value(data_dict.get("year_10", "")),
        clean_value(data_dict.get("marks_type_10", "")),
        data_dict.get("marks_10", ""),
        data_dict.get("school_12", ""),
        data_dict.get("board_12", ""),
        clean_value(data_dict.get("state_12", "")),
        clean_value(data_dict.get("year_12", "")),
        clean_value(data_dict.get("marks_type_12", "")),
        data_dict.get("marks_12", ""),
        data_dict.get("college_grad", ""),
        data_dict.get("university_grad", ""),
        clean_value(data_dict.get("state_grad", "")),
        clean_value(data_dict.get("year_grad", "")),
        clean_value(data_dict.get("marks_type_grad", "")),
        data_dict.get("marks_grad", ""),
        data_dict.get("exam_name", ""),
        clean_value(data_dict.get("exam_year", "")),
        data_dict.get("exam_score", ""),
        data_dict.get("exam_rank", ""),
        *sem_values,
        data_dict.get("intern_company", ""),
        data_dict.get("intern_role", ""),
        data_dict.get("intern_duration", ""),
        clean_value(data_dict.get("intern_state", "")),
        data_dict.get("Placed", ""),
        data_dict.get("company", ""),
        data_dict.get("role", ""),
        data_dict.get("ctc", ""),
        data_dict.get("current_address", ""),
        clean_value(data_dict.get("country", "")),
        folder_link,
        uploaded_links.get("doc_10", ""),
        uploaded_links.get("doc_12", ""),
        uploaded_links.get("doc_grad", ""),
        uploaded_links.get("exam_doc", ""),
        uploaded_links.get("Semester_1", ""),
        uploaded_links.get("Semester_2", ""),
        uploaded_links.get("Semester_3", ""),
        uploaded_links.get("Semester_4", ""),
        uploaded_links.get("Semester_5", ""),
        uploaded_links.get("Semester_6", ""),
        uploaded_links.get("Semester_7", ""),
        uploaded_links.get("Semester_8", ""),
        uploaded_links.get("intern_doc", ""),
        uploaded_links.get("offer_doc", ""),
        uploaded_links.get("address_doc", ""),
        uploaded_links.get("resume_doc", ""),
        form_status,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ]


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
        required_fields  = [d.get("school_10"), d.get("marks_10"), d.get("school_12"), d.get("marks_12"), d.get("college_grad"), d.get("marks_grad")]
        doc_10_ok   = bool(fs.get("doc_10"))   or bool(saved.get("doc_10"))
        doc_12_ok   = bool(fs.get("doc_12"))   or bool(saved.get("doc_12"))
        doc_grad_ok = bool(fs.get("doc_grad")) or bool(saved.get("doc_grad"))
        total_required = len(required_fields) + 3
        total_filled   = sum(1 for x in required_fields if x) + sum([doc_10_ok, doc_12_ok, doc_grad_ok])
        if total_filled == 0:               return "empty"
        if total_filled < total_required:   return "partial"
        return "complete"

    elif step == 3:
        sem = d.get("semester_data", [])
        if not sem: return "empty"
        total_required = len(sem) * 2
        filled = 0
        for i, s in enumerate(sem, start=1):
            if s.get("college"): filled += 1
            if fs.get(f"Semester_{i}") or saved.get(f"Semester_{i}"): filled += 1
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

    if st.button("Fetch Data"):
        if not app_id:
            st.error("Please enter an Application ID")
        else:
            # Always check BOTH tabs
            hed_data  = fetch_application_data(app_id)
            row_idx, row_data, header_row = fetch_existing_submission(app_id)

            if row_idx is not None:
                # ── Existing submission found ──────────────────────────────
                prev_student_data, prev_saved_links = parse_existing_row(row_data, header_row)

                # Merge fresh HED data on top (Name/Mobile/Email/Loan etc.)
                if hed_data:
                    for k in ["Name","Mobile","Email","LoanAmount","CourseName","CurrentLoanStatus"]:
                        if hed_data.get(k):
                            prev_student_data[k] = hed_data[k]

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
                sem_count = len(prev_student_data.get("semester_data", []))
                if sem_count > 0:
                    st.session_state.semester_count = sem_count

                # Clear stale files from any previous session
                st.session_state.file_store = {}
                st.session_state.last_submit_success = None

                folder_msg = "Drive folder restored ✅" if folder_id else "⚠️ Drive folder link missing in sheet — will create new folder on submit"
                st.success("✅ Your previously saved application has been loaded successfully.")


            elif hed_data:
                # ── New application — only in HED tab ─────────────────────
                st.session_state.student_data.update(hed_data)
                st.session_state.saved_links         = {}
                st.session_state.existing_row_index  = None
                st.session_state.drive_folder_id     = None
                st.session_state.file_store          = {}
                st.session_state.last_submit_success = None
                st.success("✅ Data Fetched Successfully")

            else:
                st.error("❌ Application ID Not Found")

    if st.session_state.existing_row_index:
        st.info(
            "📝 Edit Mode: "
            "You are updating an existing application."
        )


    name                = st.text_input("Name",                st.session_state.student_data.get("Name", ""))
    mobile              = st.text_input("Mobile",              st.session_state.student_data.get("Mobile", ""))
    email               = st.text_input("Email",               st.session_state.student_data.get("Email", ""))
    loan_amount         = st.text_input("Loan Amount",         st.session_state.student_data.get("LoanAmount", ""))
    course_name         = st.text_input("Course Name",         st.session_state.student_data.get("CourseName", ""))
    current_loan_status = st.text_input("Current Loan Status", st.session_state.student_data.get("CurrentLoanStatus", ""))

    st.session_state.student_data.update({
        "Application_ID":    app_id,
        "Name":              name,
        "Mobile":            mobile,
        "Email":             email,
        "LoanAmount":        loan_amount,
        "CourseName":        course_name,
        "CurrentLoanStatus": current_loan_status,
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

    # ── Competitive Exam ──────────────────────────────────────────────────
    st.subheader("Competitive Exam Details")
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
        "exam_name": exam_name, "exam_year": exam_year, "exam_score": exam_score, "exam_rank": exam_rank,
    })

# ================= STEP 3: Semesters =================

elif st.session_state.step == 3:
    saved = st.session_state.saved_links
    st.subheader("Course Progression - Semester Wise")

    semester_data    = st.session_state.student_data.get("semester_data", [])
    updated_semesters = []

    for i in range(1, st.session_state.semester_count + 1):
        st.markdown(f"### Semester {i}")
        existing = semester_data[i-1] if len(semester_data) >= i else {}

        college_name   = st.text_input(f"College Name (Semester {i})", value=existing.get("college", ""),    key=f"sem_college_{i}")
        course_name_s  = st.text_input(f"Course Name (Semester {i})",  value=existing.get("course", ""),     key=f"sem_course_{i}")

        year_sem = st.selectbox(f"Year (Semester {i})", year_options,
            index=year_options.index(existing.get("year", "Select Year")) if existing.get("year") in year_options else 0,
            key=f"sem_year_{i}")

        marks_type_sem = st.selectbox(f"Marks Type (Semester {i})", marks_type_options,
            index=marks_type_options.index(existing.get("marks_type", "Select")) if existing.get("marks_type") in marks_type_options else 0,
            key=f"sem_marks_type_{i}")

        sem_marks = st.text_input(f"Marks (Semester {i})", value=existing.get("marks", ""), key=f"sem_marks_{i}")

        state_sem = st.selectbox(f"State (Semester {i})", states_list,
            index=states_list.index(existing.get("state", "Select State")) if existing.get("state") in states_list else 0,
            key=f"sem_state_{i}")

        sem_key = f"Semester_{i}"
        file_status_display(sem_key, saved.get(sem_key), f"Semester {i} Marksheet")
        _f = validate_file(st.file_uploader(f"Semester {i} Marksheet", key=f"sem_doc_{i}"))
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

    st.session_state.student_data["semester_data"] = updated_semesters

    colA, colB = st.columns(2)
    with colA:
        if st.button("➕ Add Semester") and st.session_state.semester_count < 10:
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

    data  = st.session_state.student_data
    saved = st.session_state.saved_links
    fs    = st.session_state.file_store

    if st.session_state.existing_row_index:
        st.info("📝 **Update Mode** — Submitting will update the existing record.")

    # ── Basic ──────────────────────────────────────────────────────────────
    st.markdown("### 🧾 Basic Information")
    for label, key in [("Application ID","Application_ID"),("Name","Name"),("Mobile","Mobile"),
                        ("Email","Email"),("Loan Amount","LoanAmount"),("Course","CourseName"),
                        ("Loan Status","CurrentLoanStatus")]:
        st.write(f"{label}:", data.get(key, ""))
    st.markdown("---")

    # ── Education ──────────────────────────────────────────────────────────
    st.markdown("### 🎓 Education Details")
    st.write("10th:",       data.get("school_10",""), "-", data.get("marks_10",""), "-", data.get("state_10",""))
    st.write("12th:",       data.get("school_12",""), "-", data.get("marks_12",""), "-", data.get("state_12",""))
    st.write("Graduation:", data.get("college_grad",""), "-", data.get("marks_grad",""), "-", data.get("state_grad",""))
    st.write("Exam:",       data.get("exam_name",""), "-", data.get("exam_score",""))

    st.markdown("**Documents:**")
    for key, label in [("doc_10","10th Marksheet"),("doc_12","12th Marksheet"),
                        ("doc_grad","Graduation Marksheet"),("exam_doc","Exam Scorecard")]:
        if fs.get(key):
            st.write(f"  ✅ {label}: new — `{fs[key]['name']}`")
        elif saved.get(key):
            st.write(f"  📎 {label}: [View]({saved[key]})")
        else:
            st.write(f"  ⚠️ {label}: missing")
    st.markdown("---")

    # ── Semesters ──────────────────────────────────────────────────────────
    st.markdown("### 📚 Semester Details")
    for sem in data.get("semester_data", []):
        sk  = f"Semester_{sem.get('sem_no')}"
        doc = "✅ new" if fs.get(sk) else ("📎 saved" if saved.get(sk) else "⚠️ missing")
        st.write(f"Sem {sem.get('sem_no','')}: {sem.get('college','')} — {sem.get('marks','')} | Doc: {doc}")
    st.markdown("---")

    # ── Internship ─────────────────────────────────────────────────────────
    st.markdown("### 💼 Internship")
    st.write("Company:", data.get("intern_company",""))
    st.write("Role:",    data.get("intern_role",""))
    cert = "✅ new" if fs.get("intern_doc") else ("📎 saved" if saved.get("intern_doc") else "⚠️ missing")
    st.write("Certificate:", cert)
    st.markdown("---")

    # ── Placement ──────────────────────────────────────────────────────────
    st.markdown("### 🏢 Placement")
    st.write("Placed:", data.get("Placed",""))
    if data.get("Placed") == "Yes":
        st.write("Company:", data.get("company",""))
        st.write("Role:",    data.get("role",""))
        for key, label in [("offer_doc","Offer Letter"),("address_doc","Address Proof"),("resume_doc","Resume")]:
            status = "✅ new" if fs.get(key) else ("📎 saved" if saved.get(key) else "⚠️ missing")
            st.write(f"{label}: {status}")
    st.markdown("---")

    # ── Success banner ─────────────────────────────────────────────────────
    if st.session_state.get("last_submit_success"):
        st.success(st.session_state.last_submit_success)

    # ── Final Submit ───────────────────────────────────────────────────────
    if st.button("✅ Final Submit"):
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
                "doc_10", "doc_12", "doc_grad", "exam_doc",
                "intern_doc", "offer_doc", "address_doc", "resume_doc"
            ]
            doc_name_mapping = {
                "doc_10": "10th Doc",
                "doc_12": "12th Doc",
                "doc_grad": "Graduation Doc",
                "exam_doc": "Exam Doc",
                "intern_doc": "Intern Doc",
                "offer_doc": "Offer Letter",
                "address_doc": "Address Proof",
                "resume_doc": "Resume"
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
            for sem in data.get("semester_data", []):
                sem_no = sem.get("sem_no")
                sem_key = f"Semester_{sem_no}"
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
                            f"Semester_{sem_no} Doc{ext}"
                        )
                        link = upload_file_to_drive(
                            file_obj,
                            folder_id,
                            fixed_name,
                            existing_link
                        )
                        uploaded_links[sem_key] = link

            # Step 4: Save or update sheet row
            if st.session_state.existing_row_index:
                update_sheet_row(
                    st.session_state.existing_row_index,
                    data, folder_link, uploaded_links
                )
                msg = "🎉 Application Updated Successfully!"
            else:
                save_to_sheet(data, folder_link, uploaded_links)
                msg = "🎉 Application Submitted Successfully!"

            st.session_state.last_submit_success = msg

            # Step 5: Update session state so next submit is correct
            st.session_state.drive_folder_id = folder_id
            st.session_state.saved_links["folder_link"] = folder_link
            st.session_state.saved_links.update(uploaded_links)

            # If new submission, fetch the row index for future updates
            if not st.session_state.existing_row_index:
                new_row_idx, _, _ = fetch_existing_submission(data.get("Application_ID", ""))
                if new_row_idx:
                    st.session_state.existing_row_index = new_row_idx

            # Clear only file_store (not saved_links) after successful save
            st.session_state.file_store = {}

            st.rerun()

        except Exception as e:
            st.error(f"Submission Failed: {e}")

# ================= BOTTOM NAVIGATION =================

c1, c2 = st.columns(2)
if c1.button("⬅ Back") and st.session_state.step > 1:
    st.session_state.step -= 1
    st.rerun()
if c2.button("Next ➡") and st.session_state.step < 6:
    st.session_state.step += 1
    st.rerun()
