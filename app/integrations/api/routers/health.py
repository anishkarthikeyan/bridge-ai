"""Health check endpoint — used by the Docker Compose healthcheck and by any uptime monitor
placed in front of the service. Liveness only; no dependency checks (e.g. DB) at this
milestone.
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
