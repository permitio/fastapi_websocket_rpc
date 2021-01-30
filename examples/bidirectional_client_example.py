"""
This example (along with 'examples/bidirectional_server_example.py') 
builds on top of the simple example and adds- calls from the server to the client as well
"""
import asyncio
from os import wait
from fastapi_websocket_rpc import RpcMethodsBase, WebSocketRpcClient

PORT = 9000



# Methods to expose to the clients
class WaitingClient(RpcMethodsBase):

    def __init__(self):
        super().__init__()
        self.can_send_queries = asyncio.Event()
        self.can_exit = asyncio.Event()

    
    async def allow_queries(self):
        self.can_send_queries.set()
    
    async def allow_exit(self, delay):
        async def allow():
            await asyncio.sleep(delay)
            self.can_exit.set()
        asyncio.create_task(allow())
    

async def run_client(uri):
    async with WebSocketRpcClient(uri, WaitingClient()) as client:
        # wait for the server to allow us to send questions
        await client.channel.methods.can_send_queries.wait()
        # call concat on the other side
        response = await client.other.concat(a="hello", b=" world")
        # print result
        print(response.result)  # will print "hello world"
        # wait for the server to tell us we can exit
        await client.channel.methods.can_exit.wait()


if __name__ == "__main__":
    # run the client until it completes interaction with server
    asyncio.get_event_loop().run_until_complete(
        run_client(f"ws://localhost:{PORT}/ws")
    )
