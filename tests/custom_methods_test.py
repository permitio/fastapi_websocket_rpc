import time
from fastapi_websocket_rpc.utils import gen_uid
from fastapi_websocket_rpc.websocket_rpc_endpoint import WebsocketRPCEndpoint
from fastapi_websocket_rpc.websocket_rpc_client import WebSocketRpcClient
from fastapi_websocket_rpc.rpc_methods import RpcMethodsBase
from fastapi import (APIRouter, FastAPI,
                     WebSocket)
import uvicorn
import pytest
from multiprocessing import Process
import asyncio
import os
import sys


# Configurable
PORT = int(os.environ.get("PORT") or "9000")
# Random ID
CLIENT_ID = gen_uid()
uri = f"ws://localhost:{PORT}/ws/{CLIENT_ID}"


class RpcCalculator(RpcMethodsBase):

    async def add(self, a: float, b: float) -> float:
        return a + b

    async def multiply(self, a: float, b: float) -> float:
        return a * b


def setup_calc_server():
    app = FastAPI()
    router = APIRouter()
    # expose calculator methods
    endpoint = WebsocketRPCEndpoint(RpcCalculator())
    # init the endpoint

    @router.websocket("/ws/{client_id}")
    async def websocket_rpc_endpoint(websocket: WebSocket, client_id: str):
        await endpoint.main_loop(websocket, client_id)

    app.include_router(router)
    uvicorn.run(app, port=PORT)


@pytest.fixture()
def server():
    # Run the server as a separate process
    proc = Process(target=setup_calc_server, args=(), daemon=True)
    proc.start()
    yield proc
    proc.kill()  # Cleanup after test


@pytest.mark.asyncio
async def test_custom_server_methods(server):
    """
    Test rpc with calling custom methods on server sides
    """
    async with WebSocketRpcClient(uri,
                                  # we don't expose anything to the server
                                  RpcMethodsBase(),
                                  default_response_timeout=4) as client:
        import random
        a = random.random()
        b = random.random()
        response = await client.other.add(a=a, b=b)
        assert response.result == a+b
        response = await client.other.multiply(a=a, b=b)
        assert response.result == a*b
