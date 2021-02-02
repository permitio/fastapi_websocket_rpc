"""
 Test for the classic design pattern - where a client registers on the server to receive future events
"""

import os
import sys

# Add parent path to use local src as package for tests
sys.path.append(os.path.abspath(os.path.join(os.path.basename(__file__), os.path.pardir)))

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



# Configurable
PORT = int(os.environ.get("PORT") or "9000")
# Random ID
CLIENT_ID = gen_uid()
uri = f"ws://localhost:{PORT}/ws/{CLIENT_ID}"
MESSAGE = "Good morning!"


############################ Server ############################

class ServerMethods(RpcMethodsBase):

    async def register_wake_up_call(self, time_delta:float, name:str) -> str:
        async def wake_up_call():
            await asyncio.sleep(time_delta)
            await self.channel.other.wake_up(message=MESSAGE, name=name)
        asyncio.create_task(wake_up_call())
        return True

def setup_server():
    app = FastAPI()
    router = APIRouter()
    # expose server methods
    endpoint = WebsocketRPCEndpoint(ServerMethods())
    # init the endpoint

    @router.websocket("/ws/{client_id}")
    async def websocket_rpc_endpoint(websocket: WebSocket, client_id: str):
        await endpoint.main_loop(websocket, client_id)

    app.include_router(router)
    uvicorn.run(app, port=PORT)


@pytest.fixture()
def server():
    # Run the server as a separate process
    proc = Process(target=setup_server, args=(), daemon=True)
    proc.start()
    yield proc
    proc.kill()  # Cleanup after test


############################ Client ############################


class ClientMethods(RpcMethodsBase):

    def __init__(self):
        super().__init__()
        self.woke_up_event = asyncio.Event()
        self.message = None
        self.name = None

    async def wake_up(self, message=None, name=None):
        self.message = message
        self.name = name
        #signal wake-up
        self.woke_up_event.set()

@pytest.mark.asyncio
async def test_trigger_flow(server):
    """
    test cascading async trigger flow from client to sever and back
    Request the server to call us back later
    """
    async with WebSocketRpcClient(uri,
                                  ClientMethods(),
                                  default_response_timeout=4) as client:
        time_delta=0.5
        name = "Logan Nine Fingers"
        # Ask for a wake up call
        await client.other.register_wake_up_call(time_delta=time_delta, name=name)
        # Wait for our wake-up call (or fail on timeout)
        await asyncio.wait_for(client.methods.woke_up_event.wait(), 5)
        # Note: each channel has its own copy of the methods object
        assert client.channel.methods.name == name
        assert client.channel.methods.message == MESSAGE
