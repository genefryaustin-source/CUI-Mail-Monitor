from core.alerts.slack_listener import run_slack_listener
from core.storage.sqlite_ledger import SQLiteLedger   # 🔧 adjust path if different
from core.storage.local_vault import LocalVault
from core.storage.app_storage import AppStorage

if __name__ == "__main__":
    print("🚀 Starting Slack listener...")

    vault = LocalVault(root_dir="data")      # same root you use elsewhere
    ledger = SQLiteLedger(db_path="data/ledger.db")  # 🔧 match your actual path/args

    storage = AppStorage(vault=vault, ledger=ledger)

    run_slack_listener(storage)