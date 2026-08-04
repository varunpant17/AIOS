from pydantic import BaseModel


class AgentContext(BaseModel):
    user_input: str