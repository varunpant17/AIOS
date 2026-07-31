from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.repositories.user_repository import UserRepository


class UserService:

    def __init__(self):
        self.user_repository = UserRepository()

    def create_user(
        self,
        db: Session,
        email: str,
        password: str,
        full_name: str,
    ):
        hashed_password = hash_password(password)

        return self.user_repository.create_user(
            db,
            email,
            hashed_password,
            full_name,
        )

    def login_user(
        self,
        db: Session,
        email: str,
        password: str,
    ):
        user = self.user_repository.get_user_by_email(
            db,
            email,
        )

        if user is None:
            return None

        if not verify_password(
            password,
            user.hashed_password,
        ):
            return None

        access_token = create_access_token(
            {
                "sub": user.email,
            }
        )

        return {
            "access_token": access_token,
            "token_type": "bearer",
        }

    def get_users(self, db: Session):
        return self.user_repository.get_users(db)

    def get_user(
        self,
        db: Session,
        user_id: int,
    ):
        return self.user_repository.get_user(
            db,
            user_id,
        )

    def get_user_by_email(
        self,
        db: Session,
        email: str,
    ):
        return self.user_repository.get_user_by_email(
            db,
            email,
        )

    def update_user(
        self,
        db: Session,
        user_id: int,
        full_name: str,
        is_active: bool,
    ):
        return self.user_repository.update_user(
            db,
            user_id,
            full_name,
            is_active,
        )

    def delete_user(
        self,
        db: Session,
        user_id: int,
    ):
        return self.user_repository.delete_user(
            db,
            user_id,
        )