import logging
import os
import sys

# Add parent path to use local src as package for tests
sys.path.append(os.path.abspath(os.path.join(
    os.path.dirname(__file__), os.path.pardir)))

import asyncio
from multiprocessing import Process

import pytest
import uvicorn
from fastapi import FastAPI

from fastapi_websocket_rpc.rpc_methods import RpcUtilityMethods
from fastapi_websocket_rpc.logger import logging_config, LoggingModes
from fastapi_websocket_rpc.websocket_rpc_client import WebSocketRpcClient
from fastapi_websocket_rpc.websocket_rpc_endpoint import WebsocketRPCEndpoint
from fastapi_websocket_rpc.utils import gen_uid

# Set debug logs (and direct all logs to UVICORN format)
logging_config.set_mode(LoggingModes.UVICORN, logging.DEBUG)

# Configurable
PORT = int(os.environ.get("PORT") or "9000")
uri = f"ws://localhost:{PORT}/ws"


def setup_server():
    app = FastAPI()
    endpoint = WebsocketRPCEndpoint(RpcUtilityMethods())
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
    async with WebSocketRpcClient(uri, RpcUtilityMethods(), default_response_timeout=4) as client:
        text = "Hello World!"
        response = await client.other.echo(text=text)
        assert response.result == text


@pytest.mark.asyncio
async def test_ping(server):
    """
    Test basic RPC with a simple ping
    """
    async with WebSocketRpcClient(uri, RpcUtilityMethods(), default_response_timeout=4) as client:
        try:
            response = await client.other._ping_()
            passed = True
        except Exception as e:
            logging.exception("Ping test failed")
            passed = False
        assert passed


@pytest.mark.asyncio
async def test_other_channel_id(server):
    """
    Test basic RPC with a simple _get_channel_id_
    """
    async with WebSocketRpcClient(uri, RpcUtilityMethods(), default_response_timeout=4) as client:
        try:
            response = await client.other._get_channel_id_()
            assert response.result_type == 'str'
            passed = True
        except Exception as e:
            logging.exception("_get_channel_id test failed")
            passed = False
        assert passed


@pytest.mark.asyncio
async def test_keep_alive(server):
    """
    Test basic RPC with a simple echo + keep alive in the background
    """
    async with WebSocketRpcClient(uri, RpcUtilityMethods(), default_response_timeout=4, keep_alive=0.1) as client:
        text = "Hello World!"
        response = await client.other.echo(text=text)
        assert response.result == text
        await asyncio.sleep(0.6)


@pytest.mark.asyncio
async def test_structured_response(server):
    """
    Test RPC with structured (pydantic model) data response
    Using process details as example data
    """
    async with WebSocketRpcClient(uri, RpcUtilityMethods(), default_response_timeout=4) as client:
        utils = RpcUtilityMethods()
        ourProcess = await utils.get_process_details()
        response = await client.other.get_process_details()
        # We got a valid process id
        assert isinstance(response.result["pid"], int)
        # We have all the details form the other process
        assert "cmd" in response.result
