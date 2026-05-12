import time
from concurrent.futures import ThreadPoolExecutor

from core.scan.executor import run_scan_job


# ----------------------------------
# 🔥 METRIC FLUSH
# ----------------------------------
def _flush_metrics(storage, batch):
    now = int(time.time() * 1000)

    with storage.ledger._connect() as con:
        for m in batch:
            con.execute("""
                INSERT INTO metrics (name, value, ts_ms, tags_json)
                VALUES (?, ?, ?, ?)
            """, (
                m["name"],
                m["value"],
                now,
                m["tags"]
            ))
        con.commit()

    print(f"📊 Flushed {len(batch)} metrics")


# ----------------------------------
# 🔥 WORKER LOOP (FINAL)
# ----------------------------------
def _worker_loop(storage, worker_name="worker", poll_interval=2):
    ledger = storage.ledger

    print(f"🚀 {worker_name} started")
    ledger.emit_worker_event(worker_name, "STARTED", "Worker started")

    # 🔥 internal timers (prevent spam)
    last_sla_check = 0
    last_stuck_reset = 0

    while not getattr(storage, "stop_workers", False):
        try:
            now_ms = int(time.time() * 1000)

            # ----------------------------------
            # 🔥 STUCK TASK RESET (EVERY 60s)
            # ----------------------------------
            if now_ms - last_stuck_reset > 60_000:
                last_stuck_reset = now_ms
                try:
                    if hasattr(ledger, "reset_stuck_tasks"):
                        reset_count = ledger.reset_stuck_tasks()
                        if reset_count:
                            ledger.emit_worker_event(
                                worker_name,
                                "RESET_STUCK",
                                f"Reset {reset_count} stuck tasks"
                            )
                except Exception as e:
                    print(f"⚠️ stuck reset error: {e}")

            # ----------------------------------
            # 🔥 SLA BREACH DETECTION + ESCALATION
            # ----------------------------------
            try:
                # ----------------------------------
                # 🔥 INIT STATE TRACKING
                # ----------------------------------
                if not hasattr(storage, "_sla_state"):
                    storage._sla_state = {}

                if not hasattr(storage, "_sla_escalation"):
                    storage._sla_escalation = {}

                breaches = ledger.detect_queue_sla_breaches()

                grouped = {
                    "CRITICAL": [],
                    "HIGH": [],
                    "MEDIUM": []
                }

                for b in breaches:

                    task_id = b.get("task_id")
                    task_type = b.get("task_type", "UNKNOWN")
                    priority = int(b.get("priority", 5))
                    age_min = float(b.get("age_min", 0))
                    threshold = b.get("threshold_min", "?")
                    case_id = b.get("case_id")
                    owner = b.get("owner")

                    if not task_id:
                        continue

                    state_key = f"sla_{task_id}"
                    prev_state = storage._sla_state.get(state_key, "OK")

                    # ----------------------------------
                    # 🔥 FIRST BREACH ONLY
                    # ----------------------------------
                    if prev_state != "BREACHED":

                        storage._sla_state[state_key] = "BREACHED"
                        storage._sla_escalation[state_key] = now_ms

                        msg = (
                            f"Task {task_id} ({task_type}) breached SLA\n"
                            f"Age: {round(age_min, 1)} min | Threshold: {threshold}"
                        )

                        severity = "CRITICAL" if priority <= 1 else "HIGH"
                        grouped[severity].append(msg)

                        # ----------------------------------
                        # 🔥 RECORD SLA BREACH EVENT
                        # ----------------------------------
                        try:
                            if hasattr(ledger, "record_custody_event"):
                                ledger.record_custody_event(
                                    task_id,
                                    "SLA_BREACHED",
                                    {
                                        "task_id": task_id,
                                        "task_type": task_type,
                                        "priority": priority,
                                        "age_min": age_min,
                                        "threshold_min": threshold,
                                        "case_id": case_id,
                                        "owner": owner
                                    }
                                )
                        except Exception as e:
                            print(f"⚠️ SLA breach custody event error: {e}")

                        # ----------------------------------
                        # 🔥 AUTO REASSIGN TO MANAGER / ESCALATION QUEUE
                        # ----------------------------------
                        try:
                            manager_owner = "manager_queue"

                            if hasattr(ledger, "get_escalation_owner"):
                                resolved_owner = ledger.get_escalation_owner(task_id)
                                if resolved_owner:
                                    manager_owner = resolved_owner

                            if hasattr(ledger, "reassign_job"):
                                ledger.reassign_job(task_id, manager_owner)

                                if hasattr(ledger, "record_custody_event"):
                                    ledger.record_custody_event(
                                        task_id,
                                        "SLA_REASSIGNED",
                                        {
                                            "from": owner,
                                            "to": manager_owner,
                                            "reason": "SLA breach"
                                        }
                                    )

                        except Exception as e:
                            print(f"⚠️ SLA reassignment error: {e}")

                        # ----------------------------------
                        # 🔥 SLA → CASE PRIORITY BUMP
                        # ----------------------------------
                        if case_id:
                            try:
                                if hasattr(ledger, "bump_case_priority"):
                                    ledger.bump_case_priority(case_id)

                                if hasattr(ledger, "record_custody_event"):
                                    ledger.record_custody_event(
                                        task_id,
                                        "CASE_PRIORITY_BUMP",
                                        {
                                            "case_id": case_id,
                                            "reason": "SLA breach"
                                        }
                                    )

                            except Exception as e:
                                print(f"⚠️ SLA case priority bump error: {e}")

                    else:
                        # ----------------------------------
                        # 🔥 ESCALATION IF STILL BREACHED AFTER 10 MIN
                        # ----------------------------------
                        last_escalation = storage._sla_escalation.get(state_key, now_ms)

                        if now_ms - last_escalation > 600_000:

                            esc_msg = (
                                f"ESCALATION: Task {task_id} still breached\n"
                                f"Age: {round(age_min, 1)} min"
                            )

                            grouped["CRITICAL"].append(esc_msg)
                            storage._sla_escalation[state_key] = now_ms

                            try:
                                if hasattr(ledger, "record_custody_event"):
                                    ledger.record_custody_event(
                                        task_id,
                                        "SLA_HARD_ESCALATION",
                                        {
                                            "task_id": task_id,
                                            "task_type": task_type,
                                            "priority": priority,
                                            "age_min": age_min,
                                            "threshold_min": threshold,
                                            "case_id": case_id,
                                            "owner": owner
                                        }
                                    )
                            except Exception as e:
                                print(f"⚠️ SLA hard escalation event error: {e}")

                # ----------------------------------
                # 🔮 PREDICTIVE SLA BREACH DETECTION
                # ----------------------------------
                try:
                    if hasattr(ledger, "predict_sla_breaches"):

                        predictions = ledger.predict_sla_breaches()

                        for p in predictions[:5]:
                            pred_task_id = p.get("task_id") or p.get("job_id")

                            if not pred_task_id:
                                continue

                            pred_key = f"sla_predicted_{pred_task_id}"

                            if storage._sla_state.get(pred_key) == "PREDICTED":
                                continue

                            storage._sla_state[pred_key] = "PREDICTED"

                            eta_seconds = p.get("eta_seconds", "?")
                            risk = p.get("risk", "MEDIUM")

                            pred_msg = (
                                f"PREDICTED SLA BREACH: Task {pred_task_id}\n"
                                f"Risk: {risk} | ETA Remaining: {eta_seconds} sec"
                            )

                            grouped["MEDIUM"].append(pred_msg)

                            try:
                                if hasattr(ledger, "record_custody_event"):
                                    ledger.record_custody_event(
                                        pred_task_id,
                                        "SLA_PREDICTED_BREACH",
                                        p
                                    )
                            except Exception as e:
                                print(f"⚠️ SLA prediction custody event error: {e}")

                except Exception as e:
                    print(f"⚠️ Predictive SLA check error: {e}")

                # ----------------------------------
                # 🔥 SEND GROUPED ALERTS
                # ----------------------------------
                for severity, messages in grouped.items():

                    if not messages:
                        continue

                    combined_msg = "🚨 SLA ALERTS\n\n" + "\n\n".join(messages)

                    ledger.enqueue_task(
                        "NOTIFY",
                        {
                            "severity": severity,
                            "message": combined_msg,
                            "case_id": None
                        },
                        priority=1 if severity == "CRITICAL" else 2,
                        max_attempts=3
                    )

                    ledger.emit_worker_event(
                        worker_name,
                        "SLA_ALERT_BATCH",
                        f"{len(messages)} alerts grouped"
                    )

                    print(f"🚨 SLA batch alert ({severity}): {len(messages)} items")

            except Exception as e:
                print(f"⚠️ SLA check error: {e}")

            # ----------------------------------
            # CLAIM WORK
            # ----------------------------------
            job = None
            task = None

            if hasattr(ledger, "claim_next_scan_job"):
                job = ledger.claim_next_scan_job()

            if hasattr(ledger, "claim_next_task"):
                task = ledger.claim_next_task()

            # ----------------------------------
            # 🔥 SCAN JOB (PRIORITY 1)
            # ----------------------------------
            if job:
                job_id = int(job["id"])

                ledger.emit_worker_event(
                    worker_name,
                    "SCAN_STARTED",
                    f"Processing scan job {job_id}",
                    job_id=job_id
                )

                print(f"🔥 {worker_name} processing scan job {job_id}")

                try:
                    run_scan_job(storage, job_id)

                    ledger.emit_worker_event(
                        worker_name,
                        "SCAN_DONE",
                        f"Completed scan job {job_id}",
                        job_id=job_id
                    )

                except Exception as e:
                    ledger.emit_worker_event(
                        worker_name,
                        "SCAN_FAILED",
                        str(e)[:300],
                        job_id=job_id
                    )
                    print(f"❌ scan job failed: {e}")

                continue

            # ----------------------------------
            # 🔥 TASK QUEUE
            # ----------------------------------
            if task:
                print(
                    f"⚙️ {worker_name} processing task "
                    f"{task['type']} | priority={task.get('priority')} "
                    f"| attempt={task.get('attempts')}"
                )

                ledger.emit_worker_event(
                    worker_name,
                    "TASK_STARTED",
                    f"{task['type']}",
                    task_id=task["id"]
                )

                try:
                    if task["type"] == "NOTIFY":
                        from core.alerts.notifier import notify

                        notify(
                            storage,
                            task["payload"]["severity"],
                            task["payload"]["message"],
                            case_id=task["payload"].get("case_id")
                        )

                    elif task["type"] == "ESCALATE":
                        from core.cases.escalation_ladder import run_escalation_ladder
                        run_escalation_ladder(storage)

                    elif task["type"] == "METRIC_BATCH":
                        _flush_metrics(storage, task["payload"])

                    else:
                        raise ValueError(f"Unknown task type: {task['type']}")

                    # ✅ SUCCESS
                    ledger.mark_task_done(task["id"])

                    ledger.emit_worker_event(
                        worker_name,
                        "TASK_DONE",
                        f"{task['type']} complete",
                        task_id=task["id"]
                    )

                except Exception as e:
                    print(f"❌ Task error: {e}")

                    ledger.mark_task_failed(task["id"], str(e))

                    ledger.emit_worker_event(
                        worker_name,
                        "TASK_FAILED",
                        str(e)[:300],
                        task_id=task["id"]
                    )

                continue

            # ----------------------------------
            # IDLE
            # ----------------------------------
            print(f"🔍 {worker_name} idle...")
            time.sleep(poll_interval)

        except Exception as e:
            print(f"❌ {worker_name} loop error: {e}")

            ledger.emit_worker_event(
                worker_name,
                "WORKER_ERROR",
                str(e)[:300]
            )

            time.sleep(5)

    print(f"🛑 {worker_name} stopped")
    ledger.emit_worker_event(worker_name, "STOPPED", "Worker stopped")


# ----------------------------------
# 🔥 STOP WORKERS
# ----------------------------------
def stop_scan_workers(storage):
    print("🛑 Stopping workers...")
    storage.stop_workers = True


# ----------------------------------
# 🔥 START WORKERS
# ----------------------------------
def start_scan_workers(storage, max_workers=2, poll_interval=2):
    print("🚀 Starting scan workers...")

    executor = ThreadPoolExecutor(max_workers=max_workers)

    for i in range(max_workers):
        executor.submit(
            _worker_loop,
            storage,
            f"worker-{i + 1}",
            poll_interval
        )

    return executor