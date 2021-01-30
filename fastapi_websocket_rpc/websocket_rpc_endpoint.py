import asyncio
from fastapi import WebSocket, WebSocketDisconnect

from .connection_manager import ConnectionManager
from .rpc_channel import RpcChannel
from .rpc_methods import RpcMethodsBase
from .logger import get_logger

logger = get_logger("RPC_ENDPOINT")


class WebSocketSimplifier:
    """
    Simple warpper over FastAPI WebSocket to ensure unified interface for send/recv
    """

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket

    @property
    def send(self):
        return self.websocket.send_text

    @property
    def recv(self):
        return self.websocket.receive_text


class WebsocketRPCEndpoint:
    """
    A websocket RPC sever endpoint, exposing RPC methods
    """

    def __init__(self, methods: RpcMethodsBase = None, manager: ConnectionManager = None, on_disconnect=None, on_connect=None):
        """[summary]

        Args:
            methods (RpcMethodsBase): RPC methods to expose
            manager ([ConnectionManager], optional): Connection tracking object. Defaults to None (i.e. new ConnectionManager()).
            on_disconnect (coroutine, optional): Callback per disconnection 
            on_connect(coroutine, optional): Callback per connection (Server spins the callback as a new task not waiting on it.)
        """
        self.manager = manager if manager is not None else ConnectionManager()
        self.methods = methods if methods is not None else RpcMethodsBase()
        self._on_disconnect = on_disconnect
        self._on_connect = on_connect

    async def main_loop(self, websocket: WebSocket, client_id: str = None, **kwargs):
        try:
            await self.manager.connect(websocket)
            logger.info(f"Client connected", remote_address=websocket.client)
            channel = RpcChannel(self.methods, WebSocketSimplifier(websocket), **kwargs)
            channel.register_disconnect_handler(self._on_disconnect)
            await self.on_connect(channel, websocket)
            try:
                while True:
                    data = await websocket.receive_text()
                    await channel.on_message(data)
            except WebSocketDisconnect:
                logger.info(f"Client disconnected - {websocket.client.port} :: {channel.id}")
                self.manager.disconnect(websocket)
                await channel.on_disconnect()
        except:
            logger.exception(f"Failed to serve - {websocket.client.port}")
            self.manager.disconnect(websocket)

    def register_on_connect(self, callback):
        """
        Args:
            callback (function): callback to be called on each new client with the RpcChannel and the websocket
            Server spins the callback as a new task not waiting on it.
        """
        self._on_connect = callback

    async def on_connect(self, channel, websocket):
        """
        Called upon new client connection 
        """
        # Trigger connect callback if available
        if (self._on_connect is not None):
            asyncio.create_task(self._on_connect(channel, websocket))
        

    def register_route(self, router, path="/ws"):
        """
        Register this endpoint as a default websocket route on the given router
        Args:
            router: FastAPI router to load route onto
            path (str, optional): the route path. Defaults to "/ws".
        """

        @router.websocket(path)
        async def websocket_endpoint(websocket: WebSocket):
            await self.main_loop(websocket)
