from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:

    def create_user(
        self,
        db: Session,
        email: str,
        hashed_password: str,
        full_name: str,
    ):
        user = User(
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        return user

    def get_users(self, db: Session):
        return db.query(User).all()

    def get_user(self, db: Session, user_id: int):
        return (
            db.query(User)
            .filter(User.id == user_id)
            .first()
        )

    def get_user_by_email(
        self,
        db: Session,
        email: str,
    ):
        return (
            db.query(User)
            .filter(User.email == email)
            .first()
        )

    def update_user(
        self,
        db: Session,
        user_id: int,
        full_name: str,
        is_active: bool,
    ):
        user = self.get_user(db, user_id)

        if user is None:
            return None

        user.full_name = full_name
        user.is_active = is_active

        db.commit()
        db.refresh(user)

        return user

    def delete_user(
        self,
        db: Session,
        user_id: int,
    ):
        user = self.get_user(db, user_id)

        if user is None:
            return None

        db.delete(user)
        db.commit()

        return user