import os
import sys

# Add parent path to use local src as package for tests
sys.path.append(os.path.abspath(os.path.join(os.path.basename(__file__), os.path.pardir)))

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
PORT = int(os.environ.get("PORT") or "8000")
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
    async with WebSocketRpcClient(uri, RpcUtilityMethods(), retry_config=None) as client:
        text = "Hello World!"
        response = await client.other.echo(text=text)
        assert response.result == text

@pytest.mark.asyncio
async def test_structured_response(server):
    """
    Test RPC with structured data response.
    """
    async with WebSocketRpcClient(uri, RpcUtilityMethods(), retry_config=None) as client:
        utils = RpcUtilityMethods()
        ourProcess = await utils.get_proccess_details()
        response = await client.other.get_proccess_details()
        # The server is on another process
        assert response.result["pid"] != ourProcess.pid
        # We have all the details form the other process
        assert "cmd" in response.result


@pytest.mark.asyncio
async def test_recursive_response(server):
    """
    Test RPC recursive call - having the server call the client back - following the clients call
    """
    async with WebSocketRpcClient(uri, RpcUtilityMethods(), retry_config=None) as client:
        utils = RpcUtilityMethods()
        ourProcess = await utils.get_proccess_details()
        response = await client.other.echo_method(method_name="echo", args={"text":"helloworld"})
        # The server is on another process
        assert response.result == True

