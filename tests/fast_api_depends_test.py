import os
import sys
from attr import s

from websockets.exceptions import InvalidStatusCode

# Add parent path to use local src as package for tests
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))

import time 
import asyncio
from multiprocessing import Process

import pytest
import uvicorn
from fastapi import ( Response, APIRouter, Depends, FastAPI, Header, HTTPException,
                     WebSocket)

from fastapi_websocket_rpc.rpc_methods import RpcUtilityMethods
from fastapi_websocket_rpc.websocket_rpc_client import WebSocketRpcClient
from fastapi_websocket_rpc.websocket_rpc_endpoint import WebsocketRPCEndpoint
from fastapi_websocket_rpc.utils import gen_uid

# Configurable
PORT = int(os.environ.get("PORT") or "8000")
# Random ID
CLIENT_ID = gen_uid()
uri = f"ws://localhost:{PORT}/ws/{CLIENT_ID}"
# A 'secret' to be checked by the server
SECRET_TOKEN = "fake-super-secret-token"

async def check_token_header(websocket:WebSocket, x_token: str = Header(...)):
    if x_token != SECRET_TOKEN:
        await websocket.close(403)
    return None


def setup_server():
    app =  FastAPI()
    router = APIRouter()
    endpoint = WebsocketRPCEndpoint(RpcUtilityMethods())

    @router.websocket("/ws/{client_id}")
    async def websocket_rpc_endpoint(websocket: WebSocket, client_id: str, token=Depends(check_token_header)):
        await endpoint.main_loop(websocket,client_id)

    app.include_router(router)
    uvicorn.run(app, port=PORT )

@pytest.fixture()
def server():
    # Run the server as a separate process
    proc = Process(target=setup_server, args=(), daemon=True)
    proc.start()
    yield proc
    proc.kill() # Cleanup after test



@pytest.mark.asyncio
async def test_valid_token(server):
    """
    Test basic RPC with a simple echo
    """
    async with WebSocketRpcClient(uri, RpcUtilityMethods(), default_response_timeout=4, extra_headers=[("X-TOKEN", SECRET_TOKEN)]) as client:
        text = "Hello World!"
        response = await client.other.echo(text=text)
        assert response.result == text

@pytest.mark.asyncio
async def test_invalid_token(server):
    """
    Test basic RPC with a simple echo
    """
    try:
        async with WebSocketRpcClient(uri, RpcUtilityMethods(), default_response_timeout=4, extra_headers=[("X-TOKEN", "bad-token")]) as client:
            assert client is not None
            # if we got here - the server didn't reject us
            assert False
    except InvalidStatusCode as e:
        assert e.status_code == 403
