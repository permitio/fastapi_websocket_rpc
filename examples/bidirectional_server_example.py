import asyncio
import uvicorn
from fastapi import FastAPI
from fastapi_websocket_rpc import RpcMethodsBase, WebsocketRPCEndpoint
import random

# Methods to expose to the clients
class ConcatServer(RpcMethodsBase):
    async def concat(self, a="", b=""):
        # allow client to exit after some time after
        asyncio.create_task(self.channel.other.allow_exit(delay=random.randint(1,4)))
        # return calculated response
        return a + b

async def on_connect(channel, websocket):
    # Wait a bit
    await asyncio.sleep(1) 
    # now tell the client it can start sending us queries
    await channel.other.allow_queries()

    
# Init the FAST-API app
app =  FastAPI()
# Create an endpoint and load it with the methods to expose
endpoint = WebsocketRPCEndpoint(ConcatServer(), on_connect=on_connect)
# add the endpoint to the app
endpoint.register_route(app)

# Start the server itself
uvicorn.run(app, host="0.0.0.0", port=9000)