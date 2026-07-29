from sqlalchemy.orm import Session

from app.repositories.user_repository import UserRepository


class UserService:

    def __init__(self):
        self.user_repository = UserRepository()

    def create_user(
        self,
        db: Session,
        name: str,
        city: str,
    ):
        return self.user_repository.create_user(
            db,
            name,
            city,
        )

    def get_users(self, db: Session):
        return self.user_repository.get_users(db)

    def get_user(self, db: Session, user_id: int):
        return self.user_repository.get_user(db, user_id)

    def update_user(
        self,
        db: Session,
        user_id: int,
        name: str,
        city: str,
    ):
        return self.user_repository.update_user(
            db,
            user_id,
            name,
            city,
        )

    def delete_user(self, db: Session, user_id: int):
        return self.user_repository.delete_user(
            db,
            user_id,
        )