import json
from abc import ABC, abstractmethod

from .utils import pydantic_serialize


class SimpleWebSocket(ABC):
    """
    Abstract base class for all websocket related wrappers.
    """

    @abstractmethod
    def connect(self, uri: str, **connect_kwargs):
        pass

    @abstractmethod
    def send(self, msg):
        pass

    @abstractmethod
    def recv(self):
        pass

    @abstractmethod
    def close(self, code: int = 1000):
        pass

    @abstractmethod
    def handle_exception(self, exception: Exception):
        pass

    @abstractmethod
    def isConnectionClosedException(self, exception: Exception) -> bool:
        pass


class JsonSerializingWebSocket(SimpleWebSocket):
    def __init__(self, websocket: SimpleWebSocket):
        self._websocket = websocket

    async def connect(self, uri: str, **connect_kwargs):
        await self._websocket.connect(uri, **connect_kwargs)

    def _serialize(self, msg):
        return pydantic_serialize(msg)

    def _deserialize(self, buffer):
        return json.loads(buffer)

    async def send(self, msg):
        await self._websocket.send(self._serialize(msg))

    async def recv(self):
        msg = await self._websocket.recv()

        return self._deserialize(msg)

    async def close(self, code: int = 1000):
        await self._websocket.close(code)

    async def handle_exception(self, exception: Exception):
        await self._websocket.handle_exception(exception)

    async def isConnectionClosedException(self, exception: Exception) -> bool:
        return await self._websocket.isConnectionClosedException(exception)



