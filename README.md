# GhostBusters

GhostBusters is an autonomous FinOps agent for Terraform-driven cost remediation workflows.

## Environment Setup

1. Create and activate a virtual environment.
2. Copy `.env.example` to `.env` if you want to override defaults.

## Installation

```powershell
pip install -r requirements.txt
```

## Startup

```powershell
uvicorn app.main:app --reload
```

## Tests

```powershell
pytest
```

