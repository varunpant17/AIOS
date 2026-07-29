from fastapi import APIRouter

from app.schemas.health import HealthRequest
from app.schemas.message import MessageResponse

router = APIRouter(
    prefix="/health",
    tags=["Health"],
)


@router.get("/", response_model=MessageResponse)
async def health():
    return MessageResponse(message="healthy")


@router.post("/check", response_model=MessageResponse)
async def check_health(request: HealthRequest):
    return MessageResponse(
        message=f"Hello {request.name} from {request.city}, server is healthy!"
    )


@router.get("/{name}", response_model=MessageResponse)
async def greet(name: str):
    return MessageResponse(
        message=f"Hello {name}"
    )


@router.get("/search/", response_model=MessageResponse)
async def search(name: str, city: str):
    return MessageResponse(
        message=f"Hello {name} from {city}"
    )