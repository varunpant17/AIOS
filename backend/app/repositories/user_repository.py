from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:

    def create_user(self, db: Session, name: str, city: str):
        user = User(
            name=name,
            city=city,
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        return user

    def get_users(self, db: Session):
        return db.query(User).all()

    def get_user(self, db: Session, user_id: int):
        return db.query(User).filter(User.id == user_id).first()

    def delete_user(self, db: Session, user_id: int):
        user = self.get_user(db, user_id)

        if user is None:
            return None

        db.delete(user)
        db.commit()

        return user