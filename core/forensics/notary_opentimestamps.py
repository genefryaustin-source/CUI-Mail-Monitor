# core/forensics/notary_opentimestamps.py
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class OTSStampResult:
    proof_path: str
    input_path: str
    calendar_output: str


class OpenTimestampsNotary:
    """
    OpenTimestamps Notary using the `ots` CLI.

    Requirements:
      - `ots` available on PATH (from `opentimestamps-client`)
        pip install opentimestamps-client
    """

    def __init__(self, *, work_dir: str = "data/notary/ots"):
        self.work_dir = work_dir
        os.makedirs(self.work_dir, exist_ok=True)

    def _require_ots(self) -> str:
        ots = shutil.which("ots")
        if not ots:
            raise RuntimeError(
                "OpenTimestamps CLI `ots` not found on PATH.\n"
                "Install with: pip install opentimestamps-client\n"
                "Then ensure your Python Scripts directory is on PATH."
            )
        return ots

    def stamp_sha256(
        self,
        *,
        sha256_hex: str,
        label: Optional[str] = None,
    ) -> OTSStampResult:
        """
        Writes sha256_hex to a file and stamps it with OpenTimestamps.

        Produces:
          <file>.ots proof alongside the input file
        """
        ots = self._require_ots()

        safe_label = (label or "anchor").strip().replace(" ", "_")
        base = f"{safe_label}-{uuid.uuid4().hex[:10]}"
        in_path = os.path.join(self.work_dir, f"{base}.sha256.txt")

        with open(in_path, "w", encoding="utf-8") as f:
            f.write(sha256_hex.strip() + "\n")

        # `ots stamp <file>` produces <file>.ots
        try:
            proc = subprocess.run(
                [ots, "stamp", in_path],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                "OpenTimestamps stamp failed.\n"
                f"stdout:\n{e.stdout}\n\nstderr:\n{e.stderr}"
            ) from e

        proof_path = in_path + ".ots"
        if not os.path.exists(proof_path):
            raise RuntimeError(f"OpenTimestamps did not produce proof file: {proof_path}")

        return OTSStampResult(
            proof_path=proof_path,
            input_path=in_path,
            calendar_output=(proc.stdout or "").strip(),
        )

    def upgrade_proof(self, proof_path: str) -> str:
        """
        Upgrades an existing proof (may be needed later when calendars publish attestations).
        """
        ots = self._require_ots()
        try:
            proc = subprocess.run(
                [ots, "upgrade", proof_path],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                "OpenTimestamps upgrade failed.\n"
                f"stdout:\n{e.stdout}\n\nstderr:\n{e.stderr}"
            ) from e
        return (proc.stdout or "").strip()

    def verify_proof(self, proof_path: str) -> str:
        """
        Verifies a proof file.
        """
        ots = self._require_ots()
        try:
            proc = subprocess.run(
                [ots, "verify", proof_path],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                "OpenTimestamps verify failed.\n"
                f"stdout:\n{e.stdout}\n\nstderr:\n{e.stderr}"
            ) from e
        return (proc.stdout or "").strip()