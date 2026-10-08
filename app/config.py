from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    output_dir: Path

    @classmethod
    def from_environment(cls) -> "Settings":
        data_dir = Path(os.getenv("CERTIFICATE_DATA_DIR", "data")).resolve()
        return cls(
            database_path=Path(
                os.getenv("CERTIFICATE_DATABASE_PATH", data_dir / "certificates.db")
            ).resolve(),
            output_dir=Path(
                os.getenv("CERTIFICATE_OUTPUT_DIR", data_dir / "generated")
            ).resolve(),
        )

