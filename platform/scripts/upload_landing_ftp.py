import ftplib
import sys

html_path = "/home/rlopez/.gemini/antigravity-ide/brain/370eee4a-f8eb-4d44-9cc3-7be0027fa264/scratch/landing_index.html"
users = ["rlopez", "rlopez@innerchispa.us"]
password = "PCD0ct0r2026@@@"

success = False
for user in users:
    try:
        print(f"Connecting to FTP using user: {user}")
        ftp = ftplib.FTP("innerchispa.us", timeout=15)
        ftp.login(user, password)
        ftp.cwd("public_html")
        with open(html_path, "rb") as f:
            ftp.storbinary("STOR index.html", f)
        print(f"SUCCESS! Uploaded index.html using user {user}")
        ftp.quit()
        success = True
        break
    except Exception as e:
        print(f"Failed for user {user}: {e}")

if not success:
    sys.exit(1)
