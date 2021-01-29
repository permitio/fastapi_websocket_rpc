import asyncio
from fastapi_websocket_rpc import RpcMethodsBase, WebSocketRpcClient

PORT = 9000

async def run_client(uri):
    async with WebSocketRpcClient(uri, RpcMethodsBase()) as client:
        # call concat on the other side
        response = await client.other.concat(a="hello", b=" world")
        # print result
        print(response.result)  # will print "hello world"


if __name__ == "__main__":
    # run the client until it completes interaction with server
    asyncio.get_event_loop().run_until_complete(
        run_client(f"ws://localhost:{PORT}/ws")
    )
