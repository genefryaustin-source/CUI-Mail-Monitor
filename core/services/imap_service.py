import imaplib
import email
from email.header import decode_header


def connect_imap(host, username, password, port=993):
    if not host:
        raise ValueError("IMAP host is required")

    mail = imaplib.IMAP4_SSL(host, port)
    mail.login(username, password)
    return mail


def fetch_unseen_messages(mail, limit=10):
    results = []

    status, data = mail.uid('search', None, "ALL")  # 🔥 CHANGE HERE

    if status != "OK":
        print("❌ SEARCH FAILED:", status)
        return []

    msg_ids = data[0].split()
    msg_ids = msg_ids[-limit:]

    print(f"📨 RAW IDS: {msg_ids}")

    for msg_id in msg_ids:
        try:
            status, msg_data = mail.uid('fetch', msg_id, "(RFC822)")

            if status != "OK":
                print(f"❌ FETCH FAILED: {msg_id}")
                continue

            raw_email = msg_data[0][1]

            import email
            msg = email.message_from_bytes(raw_email)

            results.append({
                "uid": msg_id.decode(),
                "subject": msg.get("Subject"),
                "from": msg.get("From"),
                "message": msg
            })

        except Exception as e:
            print(f"⚠️ ERROR FETCHING {msg_id}: {e}")

    return results


def decode_mime(value):
    if not value:
        return ""
    parts = decode_header(value)
    decoded = ""
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded += part.decode(enc or "utf-8", errors="ignore")
        else:
            decoded += part
    return decoded

def extract_email_parts(msg):
    body = ""
    attachments = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition"))

            # Body
            if content_type == "text/plain" and "attachment" not in disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    body += payload.decode(errors="ignore")

            # Attachments
            if "attachment" in disposition:
                filename = part.get_filename()
                payload = part.get_payload(decode=True)

                if filename and payload:
                    attachments.append({
                        "filename": filename,
                        "data": payload
                    })
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode(errors="ignore")

    return body, attachments