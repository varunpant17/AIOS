from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.user import (
    UserCreate,
    UserUpdate,
    UserResponse,
)
from app.services.user_service import UserService

router = APIRouter(
    prefix="/users",
    tags=["Users"],
)

user_service = UserService()


@router.post(
    "",
    response_model=UserResponse,
)
def create_user(
    user: UserCreate,
    db: Session = Depends(get_db),
):
    return user_service.create_user(
        db,
        user.name,
        user.city,
    )


@router.get(
    "",
    response_model=list[UserResponse],
)
def get_users(
    db: Session = Depends(get_db),
):
    return user_service.get_users(db)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
):
    user = user_service.get_user(
        db,
        user_id,
    )

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    return user


@router.put(
    "/{user_id}",
    response_model=UserResponse,
)
def update_user(
    user_id: int,
    user: UserUpdate,
    db: Session = Depends(get_db),
):
    updated_user = user_service.update_user(
        db,
        user_id,
        user.name,
        user.city,
    )

    if updated_user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    return updated_user


@router.delete(
    "/{user_id}",
    response_model=UserResponse,
)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
):
    deleted_user = user_service.delete_user(
        db,
        user_id,
    )

    if deleted_user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    return deleted_user