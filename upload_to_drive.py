# upload_to_drive.py
import os, json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SERVICE_ACCOUNT = os.environ["GOOGLE_SERVICE_ACCOUNT"]
DRIVE_FILE_ID   = os.environ["DRIVE_FILE_ID"]
HTML_PATH       = "build/new_customers_report.html"

SCOPES = ["https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(json.loads(SERVICE_ACCOUNT), scopes=SCOPES)
drive = build("drive", "v3", credentials=creds)

media = MediaFileUpload(HTML_PATH, mimetype="text/html", resumable=False)
updated = drive.files().update(
    fileId=DRIVE_FILE_ID,
    media_body=media
).execute()

print("[OK] Drive file updated:", updated.get("id"))
print("[LINK] https://drive.google.com/file/d/{}/view?usp=sharing".format(DRIVE_FILE_ID))
