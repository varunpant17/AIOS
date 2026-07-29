from sqlalchemy.orm import Session

from app.repositories.user_repository import UserRepository


class UserService:
    def __init__(self):
        self.repository = UserRepository()

    def create_user(self, db: Session, name: str, city: str):
        return self.repository.create_user(db, name, city)

    def get_users(self, db: Session):
        return self.repository.get_users(db)

    def get_user(self, db: Session, user_id: int):
        return self.repository.get_user(db, user_id)

    def delete_user(self, db: Session, user_id: int):
        return self.repository.delete_user(db, user_id)


user_service = UserService()