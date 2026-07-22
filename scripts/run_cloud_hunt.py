"""Run one fixture-backed Cloud Hunt.

Scheduled execution is intentionally not enabled; an external scheduler can call this module later.
"""

from __future__ import annotations

import argparse

from app.models import CloudHuntRequest
from core.cloud_hunt_service import CloudHuntService


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one GhostBusters fixture-backed Cloud Hunt")
    parser.add_argument("--provider", choices=["aws", "azure", "gcp", "multi_cloud"], default="multi_cloud")
    args = parser.parse_args()
    hunt = CloudHuntService().start_hunt(CloudHuntRequest(provider_scope=args.provider))
    print(f"Cloud Hunt {hunt.id}: {hunt.status}")
    print(f"Resources scanned: {hunt.resources_scanned}")
    print(f"Candidates: {hunt.candidates_found}")
    print(f"Estimated monthly waste: ${hunt.summary.estimated_monthly_waste:.2f}")
    print("Fixture-backed only; no cloud mutation was performed.")


if __name__ == "__main__":
    main()
