"""Generate and load illustrative asset portfolios for the synthetic demo tenants.

python generate_demo_assets.py [--out data/synthetic/demo_assets.csv] [--no-load]

Needs the place table and the synthetic tenants in PostgreSQL (see generate_demo_business_data.py and
`python -m meridian.business.loader`). The work is done by meridian.business.assets.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from meridian.business.assets import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
