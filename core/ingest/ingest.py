import os
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple
import time
from core.ingest.gmail_client import (
    get_message,
    get_attachment,
    build_service_from_db,
    list_messages,
)
from core.classify.detect import detect_cui
from core.classify.document_parser import extract_text_from_bytes
from core.cases.auto_case import auto_create_case_from_alert

import base64



from core.services.imap_service import connect_imap, fetch_unseen_messages, extract_email_parts
from core.services.evidence_analysis import analyze_evidence_text
from core.utils.text_extraction import extract_text_from_bytes
# ---------------------------
# Helpers
# ---------------------------
def extract_email_body(payload):
    def walk(parts):
        for part in parts:
            mime = part.get("mimeType", "")

            # Prefer plain text
            if mime == "text/plain":
                data = part.get("body", {}).get("data")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

            # Recurse into nested parts
            if "parts" in part:
                result = walk(part["parts"])
                if result:
                    return result
        return None

    # Root payload body (sometimes Gmail puts it here)
    root_data = payload.get("body", {}).get("data")
    if root_data:
        return base64.urlsafe_b64decode(root_data).decode("utf-8", errors="ignore")

    return walk(payload.get("parts", []))


def _headers_map(payload: Dict[str, Any]) -> Dict[str, str]:
    return {
        h.get("name", ""): h.get("value", "")
        for h in payload.get("headers", [])
        if isinstance(h, dict)
    }


def _walk_parts(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    for p in parts:
        if p.get("parts"):
            found.extend(_walk_parts(p["parts"]))
        else:
            found.append(p)
    return found




def _create_cui_alert(storage, evidence_id, location, detection, source_name=None):

    # 🚨 BLOCK TEST DATA (CRITICAL FIX)
    if source_name and "FORCED TEST" in source_name:
        return None

    severity = detection.get("severity", "LOW")
    categories = detection.get("categories", ["UNKNOWN"])
    category = categories[0]

    confidence = detection.get("confidence", "LOW")
    hits = detection.get("hit_count", 0)

    matches = [h.get("match") for h in detection.get("rule_hits", [])]

    notes = json.dumps(detection)

    # ✅ Ensure debug table exists FIRST (order fix)
    with storage.ledger._connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS ui_debug_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at_ms INTEGER,
                message TEXT
            )
        """)
        con.commit()

    # Debug log BEFORE
    with storage.ledger._connect() as con:
        con.execute("""
            INSERT INTO ui_debug_log (created_at_ms, message)
            VALUES (?, ?)
        """, (
            int(time.time() * 1000),
            "🚨 ABOUT TO CREATE ALERT"
        ))
        con.commit()

    # 🔥 CREATE ALERT + CAPTURE alert_id
    with storage.ledger._connect() as con:
        cursor = con.execute("""
            INSERT INTO alerts (
                evidence_id,
                severity,
                message,
                category,
                location,
                notes,
                source_name,
                created_at_ms,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            evidence_id,
            severity,
            f"CUI detected in {location}",
            category,
            location,
            notes,
            source_name,
            int(time.time() * 1000),
            "OPEN"
        ))

        alert_id = cursor.lastrowid  # 🔥 CRITICAL FIX
        con.commit()

    # Debug log AFTER
    with storage.ledger._connect() as con:
        con.execute("""
            INSERT INTO ui_debug_log (created_at_ms, message)
            VALUES (?, ?)
        """, (
            int(time.time() * 1000),
            f"🚨 ALERT CREATED | alert_id={alert_id} | evidence_id={evidence_id} | location={location} | categories={categories}"
        ))
        con.commit()

    # 🔥 CRITICAL: LINK alert → evidence
    try:
        storage.ledger.add_alert_evidence(alert_id, evidence_id)
    except Exception as e:
        print("⚠️ Failed to link alert to evidence:", e)

    return alert_id  # 🔥 CRITICAL FIX


# ---------------------------------------
# 📎 MIME PART EXTRACTOR (RECURSIVE)
# ---------------------------------------
def extract_parts(payload):
    parts = []

    if not payload:
        return parts

    if "parts" in payload:
        for p in payload["parts"]:
            parts.extend(extract_parts(p))
    else:
        parts.append(payload)

    return parts


def ingest_message(storage, service, mailbox: str, msg_id: str, run_id: str | None = None):
    ingested = False
    evidence_created = 0
    messages_failed = 0
    msg = get_message(service, msg_id)
    payload = msg.get("payload", {})

    leaf_parts = extract_parts(payload)
    print("📎 TOTAL MIME PARTS:", len(leaf_parts))

    headers = _headers_map(payload)
    snippet = msg.get("snippet", "")

    subject = headers.get("Subject", "") or ""
    full_body = extract_email_body(payload) or ""

    body_text = f"""
    {subject}
    {snippet or ""}
    {full_body}
    """

    print("📧 EMAIL SNIPPET:", snippet[:200] if snippet else "EMPTY")

    # ---------------------------------------
    # 🔥 STORE EMAIL AS EVIDENCE (FIXED)
    # ---------------------------------------
    try:
        email_bytes = body_text.encode("utf-8")

        email_record = storage.vault.put_bytes(
            data=email_bytes,
            suggested_name=f"email_{msg['id']}.txt"
        )

        email_evidence_id = email_record.evidence_id

        # ---------------------------------------
        # ✅ INSERT INTO evidence_records
        # ---------------------------------------
        with storage.ledger._connect() as con:
            existing = con.execute("""
                SELECT 1 FROM evidence_records WHERE evidence_id = ?
            """, (email_evidence_id,)).fetchone()

            if not existing:
                con.execute("""
                    INSERT INTO evidence_records (
                        evidence_id,
                        sha256,
                        size_bytes,
                        content_type,
                        storage_uri,
                        suggested_name,
                        created_at_ms,
                        metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    email_record.evidence_id,
                    email_record.sha256,
                    email_record.size_bytes,
                    email_record.content_type,
                    email_record.storage_uri,
                    email_record.suggested_name,
                    int(time.time() * 1000),
                    json.dumps({})
                ))

                con.commit()

                # ✅ COUNT ONLY NEW EVIDENCE
                evidence_created += 1

        # ✅ MESSAGE WAS PROCESSED
        ingested = True

        # ---------------------------------------
        # ✅ INSERT CUSTODY EVENT (SEPARATE BLOCK)
        # ---------------------------------------
        try:
            with storage.ledger._connect() as con:
                con.execute("""
                    INSERT INTO custody_events (
                        run_id,
                        evidence_id,
                        event_type,
                        actor,
                        timestamp_ms,
                        details_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    run_id,
                    email_evidence_id,
                    "INGESTED",
                    "mail_ingest",
                    int(time.time() * 1000),
                    json.dumps({
                        "source": "email",
                        "mailbox": mailbox,
                        "message_id": msg["id"],
                        "subject": subject,
                    })
                ))
                con.commit()

            print("🧾 CUSTODY EVENT INSERTED:", email_evidence_id)

        except Exception as e:
            print("⚠️ Failed to insert custody event (email):", e)

    except Exception as e:
        print(f"❌ Failed to store email evidence: {e}")
        return False, msg["id"]

    # ---------------------------------------
    # DETECTION LOGIC (UPGRADED)
    # ---------------------------------------
    email_alert_created = False

    body_detection = detect_cui(body_text)
    subject_detection = detect_cui(subject)
    snippet_detection = detect_cui(snippet or "")

    def should_alert(detection):
        if not detection or not detection.get("has_cui"):
            return False

        categories = set(detection.get("categories", []))

        if "CUI" in categories:
            return True

        return detection.get("hit_count", 0) >= 2

    # ---------------------------------------
    # 🚀 MERGE + SCORE DETECTIONS (NEW)
    # ---------------------------------------

    all_detections = [body_detection, subject_detection, snippet_detection]

    # categories
    all_categories = list(set(
        c for d in all_detections if d
        for c in d.get("categories", [])
    ))

    # rule hits
    all_rule_hits = [
        h for d in all_detections if d
        for h in d.get("rule_hits", [])
    ]

    # scores (IMPORTANT)
    combined_scores = {}
    for d in all_detections:
        for k, v in d.get("scores", {}).items():
            combined_scores[k] = combined_scores.get(k, 0) + v

    # primary category
    primary_category = max(combined_scores, key=combined_scores.get) if combined_scores else None

    # final flags
    has_cui = primary_category is not None
    hit_count = sum(d.get("hit_count", 0) for d in all_detections if d)

    # ---------------------------------------
    # 🧠 RISK LEVEL
    # ---------------------------------------
    risk_level = (
        "CRITICAL" if primary_category in ["EXPORT_CONTROL", "CONTROLLED_TECHNICAL_INFORMATION"]
        else "HIGH" if primary_category in ["CUI"]
        else "MEDIUM" if primary_category in ["PII", "PHI", "FINANCIAL"]
        else "LOW"
    )

    # ---------------------------------------
    # 🔥 PERSIST DETECTION (NEW MODEL)
    # ---------------------------------------
    try:
        storage.ledger.record_event(
            event_type="EVIDENCE_CUI_ANALYSIS",
            data={
                "evidence_id": email_evidence_id,

                # 🔥 NEW FIELDS
                "source_type": "email",
                "risk_level": risk_level,

                "cui_detection": {
                    "has_cui": has_cui,
                    "primary_category": primary_category,
                    "categories": all_categories,
                    "scores": combined_scores,
                    "hit_count": hit_count,
                    "rule_hits": all_rule_hits
                }
            }
        )

        print("🧾 EVENT: EVIDENCE_CUI_ANALYSIS RECORDED")

    except Exception as e:
        print("⚠️ Failed to record CUI analysis event:", e)

    ingested = True
    # ---------------------------------------
    # BODY
    # ---------------------------------------
    if should_alert(body_detection) and not email_alert_created:
        categories = body_detection.get("categories", [])
        message = f"CUI detected in email ({', '.join(categories)})" if categories else "CUI detected in email"

        alert_id = storage.ledger.create_alert(
            evidence_id=email_evidence_id,
            severity=risk_level,
            message=message
        )

        # 🔥 CRITICAL: link alert → evidence
        storage.ledger.add_alert_evidence(alert_id, email_evidence_id)

        email_alert_created = True

    # ---------------------------------------
    # SUBJECT
    # ---------------------------------------
    if should_alert(subject_detection):
        categories = subject_detection.get("categories", [])
        message = f"CUI detected in subject ({', '.join(categories)})" if categories else "CUI detected in subject"

        alert_id = storage.ledger.create_alert(
            evidence_id=email_evidence_id,
            severity=risk_level,
            message=message
        )

        # 🔥 CRITICAL: link alert → evidence
        storage.ledger.add_alert_evidence(alert_id, email_evidence_id)

        email_alert_created = True

    # ---------------------------------------
    # SNIPPET
    # ---------------------------------------
    if should_alert(snippet_detection):
        categories = snippet_detection.get("categories", [])
        message = f"CUI detected in snippet ({', '.join(categories)})" if categories else "CUI detected in snippet"

        alert_id = storage.ledger.create_alert(
            evidence_id=email_evidence_id,
            severity=risk_level,
            message=message
        )

        # 🔥 CRITICAL: link alert → evidence
        storage.ledger.add_alert_evidence(alert_id, email_evidence_id)

        email_alert_created = True
        ingested = True

    # ---------------------------------------
    # 🔥 ATTACHMENT PROCESSING (FIXED)
    # ---------------------------------------
    leaf_parts = extract_parts(payload)

    print("📎 TOTAL MIME PARTS:", len(leaf_parts))

    ingested = False
    attachment_count = 0

    for part in leaf_parts:
        filename = part.get("filename")
        body_data = part.get("body", {})

        attach_id = body_data.get("attachmentId")
        data_inline = body_data.get("data")

        print("DEBUG msg_id:", msg_id)
        print("DEBUG filename:", filename)
        print("DEBUG attach_id:", attach_id)

        # 🚨 ONLY REAL ATTACHMENTS
        if not filename or filename.strip() == "":
            continue

        if not attach_id and not data_inline:
            continue

        try:
            print(f"📎 PROCESSING ATTACHMENT: {filename}")

            if attach_id:
                data = get_attachment(service, msg_id, attach_id)

            elif data_inline:
                import base64
                data = base64.urlsafe_b64decode(data_inline.encode("utf-8"))

            else:
                print("⚠️ No attachment data found")
                continue

        except Exception as e:
            print("⚠️ Attachment fetch failed:", e)
            continue

        attachment_count += 1

        # ---------------------------------------
        # 💾 STORE ATTACHMENT
        # ---------------------------------------
        attachment_record = storage.vault.put_bytes(
            data=data,
            suggested_name=filename or f"attachment_{attach_id}"
        )

        attachment_evidence_id = attachment_record.evidence_id

        print("📎 STORED ATTACHMENT EVIDENCE ID:", attachment_evidence_id)


        ingested = True

        # ---------------------------------------
        # ✅ INSERT INTO evidence_records (SAFE)
        # ---------------------------------------
        with storage.ledger._connect() as con:
            existing = con.execute("""
                SELECT 1 FROM evidence_records WHERE evidence_id = ?
            """, (attachment_record.evidence_id,)).fetchone()

            if not existing:
                con.execute("""
                    INSERT INTO evidence_records (
                        evidence_id,
                        sha256,
                        size_bytes,
                        content_type,
                        storage_uri,
                        suggested_name,
                        created_at_ms,
                        metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    attachment_record.evidence_id,
                    attachment_record.sha256,
                    attachment_record.size_bytes,
                    attachment_record.content_type,
                    attachment_record.storage_uri,
                    attachment_record.suggested_name,
                    int(time.time() * 1000),
                    json.dumps({
                        "parent_email_evidence_id": email_evidence_id,
                        "source": "attachment",
                        "filename": filename,
                        "message_id": msg_id,
                        "mailbox": mailbox,
                    })
                ))

                con.commit()

                # ✅ ONLY COUNT IF NEW
                evidence_created += 1

            # ---------------------------------------
            # ✅ ATTACHMENT CUSTODY EVENT
            # ---------------------------------------
            with storage.ledger._connect() as con:
                con.execute("""
                    INSERT INTO custody_events (
                        run_id,
                        evidence_id,
                        event_type,
                        actor,
                        timestamp_ms,
                        details_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    run_id,
                    attachment_evidence_id,
                    "INGESTED",
                    "mail_ingest",
                    int(time.time() * 1000),
                    json.dumps({
                        "source": "attachment",
                        "mailbox": mailbox,
                        "message_id": msg["id"],
                        "filename": filename,
                        "parent_email_evidence_id": email_evidence_id,
                    })
                ))
                con.commit()

            print("🧾 ATTACHMENT CUSTODY EVENT INSERTED:", attachment_evidence_id)
            try:
                storage.ledger.record_custody_event(
                    run_id=run_id,
                    evidence_id=attachment_evidence_id,
                    event_type="INGESTED",
                    actor="mail_ingest",
                    details={
                        "source": "attachment",
                        "mailbox": mailbox,
                        "message_id": msg["id"],
                        "filename": filename,
                    }
                )
                print("🧾 CUSTODY EVENT RECORDED:", attachment_evidence_id)
            except Exception as e:
                print("⚠️ Failed to record custody event (attachment):", e)
            print("📎 STORED ATTACHMENT EVIDENCE ID:", attachment_evidence_id)

            extracted_text = extract_text_from_bytes(data, filename)

            # ----------------------------
            # 📄 DEBUG VISIBILITY
            # ----------------------------
            print("📄 TEXT LENGTH:", len(extracted_text) if extracted_text else 0)
            print("📄 TEXT SAMPLE:", extracted_text[:200] if extracted_text else "EMPTY")

            # ----------------------------
            # 🚨 HARD GUARD (CRITICAL)
            # ----------------------------
            if not extracted_text or extracted_text == "[NO TEXT EXTRACTED]":
                extraction_warning = True
            else:
                extraction_warning = False

            # ----------------------------
            # 🧠 DETECTION (CUI + FLAGS)
            # ----------------------------
            combined_text = f"{filename} {extracted_text or ''}"
            analysis = analyze_evidence_text(combined_text)

            if not isinstance(analysis, dict):
                print("🚨 BAD ANALYSIS TYPE:", type(analysis))
                analysis = {"flags": [], "matches": [], "rule_hits": []}

            print("🧠 ANALYSIS:", analysis)

            attachment_evidence = {
                "text": extracted_text,
                "filename": filename,
                "source": "attachment",
                "rule_hits": analysis.get("rule_hits", []),
                "flags": analysis.get("flags", []),
                "matches": analysis.get("matches", []),
                "extraction_warning": extraction_warning
            }




            attachment_detection = {
                "has_cui": analysis.get("has_cui", False),
                "categories": analysis.get("flags", []),
                "hit_count": analysis.get("hit_count", 0),
                "rule_hits": analysis.get("rule_hits", [])
            }

            if should_alert(attachment_detection):

                # ----------------------------------
                # 🧾 RECORD EVENT (ISOLATED)
                # ----------------------------------
                try:
                    primary = analysis.get("primary_category")

                    storage.ledger.record_event(
                        event_type="ATTACHMENT_CUI_ANALYSIS",
                        data={
                            "parent_evidence_id": email_evidence_id,
                            "attachment_evidence_id": attachment_evidence_id,
                            "filename": filename,

                            # ----------------------------------
                            # 🧠 NEW INTELLIGENCE FIELDS (TOP LEVEL)
                            # ----------------------------------
                            "source_type": "attachment",
                            "risk_level": (
                                "CRITICAL" if primary in ["EXPORT_CONTROL", "CONTROLLED_TECHNICAL_INFORMATION"]
                                else "HIGH" if primary in ["CUI"]
                                else "MEDIUM" if primary in ["PII", "PHI", "FINANCIAL"]
                                else "LOW"
                            ),

                            # ----------------------------------
                            # 🔍 DETECTION PAYLOAD
                            # ----------------------------------
                            "cui_detection": {
                                "has_cui": analysis.get("has_cui", False),
                                "primary_category": primary,
                                "categories": analysis.get("categories", []),
                                "scores": analysis.get("scores", {}),
                                "hit_count": analysis.get("hit_count", 0),
                                "rule_hits": analysis.get("rule_hits", []),
                                "matches": analysis.get("matches", [])
                            }
                        }
                    )

                except Exception as e:
                    print("❌ EVENT INSERT FAILED (ATTACHMENT):", e)
                else:
                    print("🧾 EVENT: ATTACHMENT_CUI_ANALYSIS RECORDED")






                categories = analysis.get("flags", [])

                message = (
                    f"CUI detected in attachment ({', '.join(categories)})"
                    if categories else "CUI detected in attachment"
                )

                alert_id = storage.ledger.create_alert(
                    evidence_id=attachment_evidence_id,
                    severity=risk_level,
                    message=message
                )

                # 🔥 CRITICAL: link alert → evidence
                storage.ledger.add_alert_evidence(alert_id, attachment_evidence_id)
            evidence_created += 1

    print("📎 TOTAL ATTACHMENTS PROCESSED:", attachment_count)

    # ✅ FINAL RETURN (CRITICAL — THIS WAS MISSING)
    return {
        "messages_processed": 1,
        "messages_failed": messages_failed,
        "evidence_created": evidence_created
    }



def run_ingest(
    storage,
    provider: str,
    mailbox: str,
    lookback_hours: int = 168,
    attachments_only: bool = True,
    max_messages: int = 100,
    payload: dict | None = None,
    job_id: str | None = None,
):
    ledger = storage.ledger

    if provider == "imap":



        print("📡 IMAP INGEST STARTED")

        print("🔌 CONNECTING TO IMAP...")


        print("✅ IMAP CONNECTED")



        config = payload or {}

        mail = connect_imap(
            config.get("host"),
            config.get("username"),
            config.get("password"),
        )
        print("📂 SELECTING MAILBOX...")
        mail.select(mailbox or "INBOX")

        print("📡 FETCHING MESSAGES...")
        messages = fetch_unseen_messages(mail, limit=max_messages)

        print(f"📨 FETCHED {len(messages)} EMAILS")


        print(f"📨 FETCHED {len(messages)} EMAILS")

        case = {"evidence": []}

        for m in messages:
            msg = m["message"]
            subject = m.get("subject", "")
            body, attachments = extract_email_parts(msg)

            print("📧 PROCESSING:", m.get("subject"))

            # ----------------------------
            # 📄 EMAIL BODY
            # ----------------------------
            if body:
                combined_text = f"{subject} {body or ''}"

                analysis = analyze_evidence_text(combined_text)

                if not isinstance(analysis, dict):
                    print("🚨 BAD ANALYSIS TYPE:", type(analysis))
                    analysis = {"flags": [], "matches": [], "rule_hits": []}

                case["evidence"].append({
                    "score": 0,
                    "evidence": {
                        "text": body,
                        "filename": "email_body",
                        "source": "imap",
                        "rule_hits": analysis.get("rule_hits", []),
                        "flags": analysis.get("flags", []),
                        "matches": analysis.get("matches", []),
                    }
                })

            # ----------------------------
            # 📎 ATTACHMENTS
            # ----------------------------
            for att in attachments:
                try:
                    filename = att.get("filename", "unknown")
                    data = att.get("data")

                    extracted_text = extract_text_from_bytes(data, filename)

                    combined_text = f"{filename} {extracted_text or ''}"
                    analysis = analyze_evidence_text(combined_text)

                    if not isinstance(analysis, dict):
                        print("🚨 BAD ANALYSIS TYPE:", type(analysis))
                        analysis = {"flags": [], "matches": [], "rule_hits": []}



                    case["evidence"].append({
                        "score": 0,
                        "evidence": {
                            "text": extracted_text,
                            "filename": filename,
                            "source": "imap_attachment",
                            "rule_hits": analysis.get("rule_hits", []),
                            "flags": analysis.get("flags", []),
                            "matches": analysis.get("matches", []),
                        }
                    })

                except Exception as e:
                    print(f"⚠️ Attachment processing failed: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

        return case

    def _get_status():
        if not job_id:
            return None
        with ledger._connect() as con:
            row = con.execute(
                "SELECT status FROM scan_queue WHERE id=?",
                (job_id,),
            ).fetchone()
        return row[0] if row else None

    if provider != "gmail":
        raise ValueError(f"Unsupported provider: {provider}")

    # ----------------------------------
    # 🔥 CRITICAL FIX:
    # Custody events require a valid run_id FK.
    # Ensure the run exists BEFORE ingest_message writes events.
    # ----------------------------------
    #run_id = str(job_id) if job_id else f"manual-{int(time.time() * 1000)}"
    run_id = f"run-{job_id}-{int(time.time() * 1000)}" if job_id else f"manual-{int(time.time() * 1000)}"

    if hasattr(ledger, "ensure_run"):
        try:
            ledger.ensure_run(
                run_id=run_id,
                provider=provider,
                mailbox=mailbox
            )
            print("🧾 RUN ENSURED:", run_id)
        except Exception as e:
            print("⚠️ Failed to ensure run:", e)

    service = build_service_from_db(storage, mailbox)

    query = f"in:inbox newer_than:{lookback_hours}h"

    message_ids = list_messages(
        service,
        max_results=max_messages,
        query=query,
    )

    print(f"📬 Query: {query}")
    print(f"📬 Messages found: {len(message_ids)}")

    total = len(message_ids)
    processed = 0
    failed = 0
    evidence_created = 0

    for msg_id in message_ids:

        if _get_status() == "CANCELLED":
            print(f"🛑 Scan canceled at message {processed}/{total}")
            return {
                "status": "CANCELLED",
                "messages_processed": processed,
                "messages_failed": failed,
                "evidence_created": evidence_created,
            }

        try:
            result = ingest_message(storage, service, mailbox, msg_id, run_id)

            if isinstance(result, dict):
                processed += result.get("messages_processed", 0)
                failed += result.get("messages_failed", 0)
                evidence_created += result.get("evidence_created", 0)
                print("DEBUG RESULT:", result)
            else:
                print("⚠️ Unexpected ingest result:", result)

        except Exception as e:
            print(f"❌ Failed processing message {msg_id}: {e}")
            failed += 1

        # 🔥 FIX PROGRESS DISPLAY
        display_processed = min(processed, total)
        print(f"📈 PROGRESS UPDATE → {display_processed}/{total}")

        if job_id and hasattr(ledger, "update_scan_progress"):
            ledger.update_scan_progress(
                job_id,
                current=display_processed,
                total=max(total, 1),
            )

    return {
        "status": "COMPLETED",
        "messages_processed": processed,
        "messages_failed": failed,
        "evidence_created": evidence_created,
        "total_messages": total,
    }

