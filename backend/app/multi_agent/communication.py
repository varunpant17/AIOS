from threading import RLock

from pydantic import ValidationError

from app.multi_agent.errors import (
    A2ACommunicationError,
    AgentNotFoundError,
    InvalidAgentMessageError,
)
from app.multi_agent.interfaces import AgentRegistry
from app.multi_agent.types import AgentMessage


class InMemoryA2AChannel:
    """Thread-safe process-local mailboxes for validated agent messages."""

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry
        self._inboxes: dict[str, list[AgentMessage]] = {}
        self._lock = RLock()

    def send(self, message: AgentMessage) -> None:
        try:
            validated = AgentMessage.model_validate(message)
        except (ValidationError, TypeError, ValueError) as exc:
            raise InvalidAgentMessageError("A2A message is invalid.") from exc
        try:
            self._registry.get(validated.sender_agent_id)
            self._registry.get(validated.recipient_agent_id)
        except AgentNotFoundError as exc:
            raise A2ACommunicationError("Message sender or recipient is not registered.") from exc
        except Exception as exc:
            raise A2ACommunicationError("Message recipient could not be resolved.") from exc
        with self._lock:
            inbox = self._inboxes.setdefault(validated.recipient_agent_id, [])
            if any(item.message_id == validated.message_id for item in inbox):
                raise A2ACommunicationError("Duplicate message identifier.")
            inbox.append(validated.model_copy(deep=True))

    def receive(self, recipient_agent_id: str, *, task_id: str) -> AgentMessage:
        if (
            not isinstance(recipient_agent_id, str)
            or not recipient_agent_id.strip()
            or not isinstance(task_id, str)
            or not task_id.strip()
        ):
            raise A2ACommunicationError("Recipient and task identifiers are required.")
        with self._lock:
            inbox = self._inboxes.get(recipient_agent_id, [])
            for index, message in enumerate(inbox):
                if message.task_id == task_id:
                    return inbox.pop(index).model_copy(deep=True)
        raise A2ACommunicationError("No delivered message exists for this task.")
