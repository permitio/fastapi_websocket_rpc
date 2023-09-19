import logging
import os
import sys

# Add parent path to use local src as package for tests
sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
)

import json
from multiprocessing import Process

import pytest
import uvicorn
from fastapi import FastAPI

from fastapi_websocket_rpc import WebSocketFrameType
from fastapi_websocket_rpc.logger import LoggingModes, logging_config
from fastapi_websocket_rpc.rpc_methods import RpcUtilityMethods
from fastapi_websocket_rpc.simplewebsocket import SimpleWebSocket
from fastapi_websocket_rpc.utils import pydantic_serialize
from fastapi_websocket_rpc.websocket_rpc_client import WebSocketRpcClient
from fastapi_websocket_rpc.websocket_rpc_endpoint import WebsocketRPCEndpoint

# Set debug logs (and direct all logs to UVICORN format)
logging_config.set_mode(LoggingModes.UVICORN, logging.DEBUG)

# Configurable
PORT = int(os.environ.get("PORT") or "9000")
uri = f"ws://localhost:{PORT}/ws"


class BinarySerializingWebSocket(SimpleWebSocket):
    def __init__(self, websocket: SimpleWebSocket):
        self._websocket = websocket

    def _serialize(self, msg):
        return pydantic_serialize(msg).encode()

    def _deserialize(self, buffer):
        return json.loads(buffer.decode())

    async def send(self, msg):
        await self._websocket.send(self._serialize(msg))

    async def recv(self):
        msg = await self._websocket.recv()

        return self._deserialize(msg)

    async def close(self, code: int = 1000):
        await self._websocket.close(code)


def setup_server():
    app = FastAPI()
    endpoint = WebsocketRPCEndpoint(
        RpcUtilityMethods(),
        frame_type=WebSocketFrameType.Binary,
        serializing_socket_cls=BinarySerializingWebSocket,
    )
    endpoint.register_route(app)
    uvicorn.run(app, port=PORT)


@pytest.fixture(scope="module")
def server():
    # Run the server as a separate process
    proc = Process(target=setup_server, args=(), daemon=True)
    proc.start()
    yield proc
    proc.kill()  # Cleanup after test


@pytest.mark.asyncio
async def test_echo(server):
    """
    Test basic RPC with a simple echo
    """
    async with WebSocketRpcClient(
        uri,
        RpcUtilityMethods(),
        default_response_timeout=4,
        serializing_socket_cls=BinarySerializingWebSocket,
    ) as client:
        text = "Hello World!"
        response = await client.other.echo(text=text)
        assert response.result == text


@pytest.mark.asyncio
async def test_structured_response(server):
    """
    Test RPC with structured (pydantic model) data response
    Using process details as example data
    """
    async with WebSocketRpcClient(
        uri,
        RpcUtilityMethods(),
        default_response_timeout=4,
        serializing_socket_cls=BinarySerializingWebSocket,
    ) as client:
        utils = RpcUtilityMethods()
        ourProcess = await utils.get_process_details()
        response = await client.other.get_process_details()
        # We got a valid process id
        assert isinstance(response.result["pid"], int)
        # We have all the details form the other process
        assert "cmd" in response.result
