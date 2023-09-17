import json
from abc import ABC, abstractmethod

from .utils import get_model_serializer


class SimpleWebSocket(ABC):
    """
    Abstract base class for all websocket related wrappers.
    """

    @abstractmethod
    def send(self, msg):
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

    def _serialize(self, msg):
        serialize_model = get_model_serializer()
        return serialize_model(msg)

    def _deserialize(self, buffer):
        return json.loads(buffer)

    async def send(self, msg):
        await self._websocket.send(self._serialize(msg))

    async def recv(self):
        msg = await self._websocket.recv()

        return self._deserialize(msg)

    async def close(self, code: int = 1000):
        await self._websocket.close(code)
