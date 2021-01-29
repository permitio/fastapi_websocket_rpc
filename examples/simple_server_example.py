import uvicorn
from fastapi import FastAPI
from fastapi_websocket_rpc import RpcMethodsBase, WebsocketRPCEndpoint

# Methods to expose to the clients
class ConcatServer(RpcMethodsBase):
    async def concat(self, a="", b=""):
        return a + b
    
# Init the FAST-API app
app =  FastAPI()
# Create an endpoint and load it with the methods to expose
endpoint = WebsocketRPCEndpoint(ConcatServer())
# add the endpoint to the app
endpoint.register_route(app)

# Start the server itself
uvicorn.run(app, host="0.0.0.0", port=9000)