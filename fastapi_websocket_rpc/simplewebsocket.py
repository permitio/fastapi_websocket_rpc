import json
from abc import ABC, abstractmethod

from .logger import get_logger
from .utils import pydantic_serialize

logger = get_logger("fastapi_websocket_rpc.simplewebsocket")


class SimpleWebSocket(ABC):
    """
    Abstract base class for all websocket related wrappers.
    """

    @abstractmethod
    def send(self, message):
        pass

    @abstractmethod
    def recv(self):
        pass

    @abstractmethod
    def close(self, code: int = 1000):
        pass


class JsonSerializingWebSocket(SimpleWebSocket):
    def __init__(self, websocket: SimpleWebSocket):
        self._websocket = websocket

    def _serialize(self, message):
        return pydantic_serialize(message)

    def _deserialize(self, buffer):
        logger.debug(f"Deserializing message: {buffer}")
        return json.loads(buffer)

    async def send(self, message):
        await self._websocket.send(self._serialize(message))

    async def recv(self):
        logger.debug("Waiting for message...")
        message = await self._websocket.recv()
        logger.debug(f"Received message: {message}")
        return self._deserialize(message)

    async def close(self, code: int = 1000):
        await self._websocket.close(code)
