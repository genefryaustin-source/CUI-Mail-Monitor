import time
import queue
import threading

from core.alerts.notifier import notify
from core.cases.escalation_ladder import run_escalation_ladder

WORK_QUEUE = queue.Queue()


def enqueue_task(task_type, payload):
    WORK_QUEUE.put((task_type, payload))


def worker_loop(storage):
    print("🚀 Case worker started")

    while True:
        try:
            task_type, payload = WORK_QUEUE.get()

            if task_type == "NOTIFY":
                notify(
                    storage,
                    payload["severity"],
                    payload["message"],
                    case_id=payload.get("case_id")
                )

            elif task_type == "ESCALATE":
                run_escalation_ladder(storage)

            WORK_QUEUE.task_done()

        except Exception as e:
            print("❌ Worker error:", e)

        time.sleep(0.05)


def start_worker(storage):
    t = threading.Thread(target=worker_loop, args=(storage,), daemon=True)
    t.start()