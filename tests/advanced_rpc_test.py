import os
import sys

import time 
import asyncio
from multiprocessing import Process

import pytest
import uvicorn
from fastapi import (APIRouter, Depends, FastAPI, Header, HTTPException,
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


def setup_server():
    app = FastAPI()
    router = APIRouter()
    endpoint = WebsocketRPCEndpoint(RpcUtilityMethods())

    @router.websocket("/ws/{client_id}")
    async def websocket_rpc_endpoint(websocket: WebSocket, client_id: str):
        await endpoint.main_loop(websocket, client_id)

    app.include_router(router)
    uvicorn.run(app, port=PORT)


@pytest.fixture(scope="module")
def server():
    # Run the server as a separate process
    proc = Process(target=setup_server, args=(), daemon=True)
    proc.start()
    yield proc
    proc.kill()  # Cleanup after test


@pytest.mark.asyncio
async def test_recursive_rpc_calls(server):
    """
    Test RPC recursive call - having the server call the client back - following the clients call
    this recursion isn't useful by itself - but it does test several mechanisms:
        - bi-directional cascading calls 
        - follow-up calls
        - remote promise access
    """
    async with WebSocketRpcClient(uri, RpcUtilityMethods(), default_response_timeout=4) as client:
        text = "recursive-helloworld"
        utils = RpcUtilityMethods()
        ourProcess = await utils.get_process_details()
        # we call the server's call_me_back, asking him to call our echo method
        remote_promise = await client.other.call_me_back(method_name="echo", args={"text": text})
        # give the server a chance to call us
        await asyncio.sleep(1)
        # go back to the server to get our own response from it
        response = await client.other.get_response(call_id=remote_promise.result)
        # check the response we sent
        assert response.result['result'] == text
