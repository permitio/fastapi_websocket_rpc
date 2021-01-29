import os
import sys

# Add parent path to use local src as package for tests
sys.path.append(os.path.abspath(os.path.join(os.path.basename(__file__), os.path.pardir)))

import time 
import asyncio
from multiprocessing import Process

import pytest
import uvicorn
from fastapi import (APIRouter, Depends, FastAPI, Header, HTTPException,
                     WebSocket)
from starlette import responses

from fastapi_websocket_rpc.rpc_methods import RpcUtilityMethods
from fastapi_websocket_rpc.websocket_rpc_client import WebSocketRpcClient
from fastapi_websocket_rpc.websocket_rpc_endpoint import WebsocketRPCEndpoint
from fastapi_websocket_rpc.utils import gen_uid

# Configurable
PORT = int(os.environ.get("PORT") or "9000")
# Random ID
CLIENT_ID = gen_uid()
uri = f"ws://localhost:{PORT}/ws/{CLIENT_ID}"


def setup_server():
    app =  FastAPI()
    router = APIRouter()
    endpoint = WebsocketRPCEndpoint(RpcUtilityMethods())

    @router.websocket("/ws/{client_id}")
    async def websocket_rpc_endpoint(websocket: WebSocket, client_id: str):
        await endpoint.main_loop(websocket,client_id)

    app.include_router(router)
    uvicorn.run(app, port=PORT )


@pytest.fixture(scope="module")
def server():
    # Run the server as a separate process
    proc = Process(target=setup_server, args=(), daemon=True)
    proc.start()
    yield proc
    proc.kill() # Cleanup after test

@pytest.mark.asyncio
async def test_echo(server):
    """
    Test basic RPC with a simple echo
    """
    async with WebSocketRpcClient(uri, RpcUtilityMethods(), default_response_timeout=4) as client:
        text = "Hello World!"
        response = await client.other.echo(text=text)
        assert response.result == text

@pytest.mark.asyncio
async def test_structured_response(server):
    """
    Test RPC with structured (pydantic model) data response
    Using process details as example data
    """
    async with WebSocketRpcClient(uri, RpcUtilityMethods(), default_response_timeout=4) as client:
        utils = RpcUtilityMethods()
        ourProcess = await utils.get_proccess_details()
        response = await client.other.get_proccess_details()
        # The server is on another process
        assert response.result["pid"] != ourProcess.pid
        # We have all the details form the other process
        assert "cmd" in response.result
