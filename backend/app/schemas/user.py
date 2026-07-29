from pydantic import BaseModel, ConfigDict


class UserCreate(BaseModel):
    name: str
    city: str


class UserResponse(BaseModel):
    id: int
    name: str
    city: str

    model_config = ConfigDict(from_attributes=True)