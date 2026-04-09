from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    from app.main import get_uptime

    return {
        "status": "ok",
        "version": "0.1.0",
        "uptime_seconds": round(get_uptime(), 1),
    }
