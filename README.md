<p align="center">
<img src="https://i.ibb.co/m8jL6Zd/RPC.png" alt="RPC" border="0" width="50%" />
</p>

#

# ⚡ FASTAPI Websocket RPC
RPC over Websockets made easy, robust, and production ready

<a href="https://github.com/permitio/fastapi_websocket_rpc/actions?query=workflow%3ATests" target="_blank">
    <img src="https://github.com/permitio/fastapi_websocket_rpc/workflows/Tests/badge.svg" alt="Tests">
</a>

<a href="https://pypi.org/project/fastapi-websocket-rpc/" target="_blank">
    <img src="https://img.shields.io/pypi/v/fastapi-websocket-rpc?color=%2331C654&label=PyPi%20package" alt="Package">
</a>

<a href="https://pepy.tech/project/fastapi-websocket-rpc" target="_blank">
    <img src="https://static.pepy.tech/personalized-badge/fastapi-websocket-rpc?period=total&units=international_system&left_color=black&right_color=blue&left_text=Downloads" alt="Downloads">
</a>

A fast and durable bidirectional JSON RPC channel over Websockets.
The easiest way to create a live async channel between two nodes via Python (or other clients).

- Both server and clients can easily expose Python methods that can be called by the other side.
Method return values are sent back as RPC responses, which the other side can wait on.
- Remote methods are easily called via the ```.other.method()``` wrapper 
- Connections are kept alive with a configurable retry mechanism  (using Tenacity)

- As seen at <a href="https://www.youtube.com/watch?v=KP7tPeKhT3o" target="_blank">PyCon IL 2021</a> and <a href="https://www.youtube.com/watch?v=IuMZVWEUvGs" target="_blank">EuroPython 2021</a>


Supports and tested on Python >= 3.9 
## Installation 🛠️
```
pip install fastapi_websocket_rpc
```


## RPC call example:

Say the server exposes an "add" method, e.g. :
```python
class RpcCalculator(RpcMethodsBase):
    async def add(self, a, b):
        return a + b
```
Calling it is as easy as calling the method under the client's "other" property:
```python
response = await client.other.add(a=1,b=2)
print(response.result) # 3
```
getting the response with the return value.




## Usage example:

### Server:
```python
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
endpoint.register_route(app, "/ws")

# Start the server itself
uvicorn.run(app, host="0.0.0.0", port=9000)
```
### Client
```python
import asyncio
from fastapi_websocket_rpc import RpcMethodsBase, WebSocketRpcClient

async def run_client(uri):
    async with WebSocketRpcClient(uri, RpcMethodsBase()) as client:
        # call concat on the other side
        response = await client.other.concat(a="hello", b=" world")
        # print result
        print(response.result)  # will print "hello world"

# run the client until it completes interaction with server
asyncio.get_event_loop().run_until_complete(
    run_client("ws://localhost:9000/ws")
)
```

See the [examples](/examples) and [tests](/tests) folders for more server and client examples


## Server calling client example:
- Clients can call ```client.other.method()``` 
    - which is a shortcut for ```channel.other.method()```
- Servers also get the channel object and can call remote methods via ```channel.other.method()```
- See the [bidirectional call example](examples/bidirectional_server_example.py) for calling client from server and server events (e.g. ```on_connect```).


## What can I do with this?
Websockets are ideal to create bi-directional realtime connections over the web.
 - Push updates
 - Remote control mechanism
 - Pub / Sub (see [fastapi_websocket_pubsub](https://github.com/permitio/fastapi_websocket_pubsub))
 - Trigger events (see "tests/trigger_flow_test.py")
 - Node negotiations (see "tests/advanced_rpc_test.py :: test_recursive_rpc_calls")


## Concepts
- [RpcChannel](fastapi_websocket_rpc/rpc_channel.py) - implements the RPC-protocol over the websocket
    - Sending RpcRequests per method call 
    - Creating promises to track them (via unique call ids), and allow waiting for responses 
    - Executing methods on the remote side and serializing return values as    
    - Receiving RpcResponses and delivering them to waiting callers
- [RpcMethods](fastapi_websocket_rpc/rpc_methods.py) - classes passed to both client and server-endpoint inits to expose callable methods to the other side.
    - Simply derive from RpcMethodsBase and add your own async methods
    - Note currently only key-word arguments are supported
    - Checkout RpcUtilityMethods for example methods, which are also useful debugging utilities


- Foundations:

    - Based on [asyncio](https://docs.python.org/3/library/asyncio.html) for the power of Python coroutines

    - Server Endpoint:
        - Based on [FAST-API](https://github.com/tiangolo/fastapi): enjoy all the benefits of a full ASGI platform, including Async-io and dependency injections (for example to authenticate connections)

        - Based on [Pydantic](https://pydantic-docs.helpmanual.io/): easily serialize structured data as part of RPC requests and responses (see 'tests/basic_rpc_test.py :: test_structured_response' for an example)

    - Client :
        - Based on [Tenacity](https://tenacity.readthedocs.io/en/latest/index.html): allowing configurable retries to keep to connection alive
            - see WebSocketRpcClient.__init__'s retry_config 
        - Based on python [websockets](https://websockets.readthedocs.io/en/stable/intro.html) - a more comprehensive client than the one offered by Fast-api

## Logging 
fastapi-websocket-rpc provides a helper logging module to control how it produces logs for you.
See [fastapi_websocket_rpc/logger.py](fastapi_websocket_rpc/logger.py).
Use ```logging_config.set_mode``` or the 'WS_RPC_LOGGING' environment variable to choose the logging method you prefer or override completely via default logging config.

example:
```python
# set RPC to log like UVICORN
from fastapi_websocket_rpc.logger import logging_config, LoggingModes
logging_config.set_mode(LoggingModes.UVICORN)
```

## HTTP(S) Proxy
By default, fastapi-websocket-rpc uses websockets module as websocket client handler. This does not support HTTP(S) Proxy, see https://github.com/python-websockets/websockets/issues/364 . If the ability to use a proxy is important to, another websocket client implementation can be used, e.g. websocket-client (https://websocket-client.readthedocs.io). Here is how to use it. Installation:

```
pip install fastapi_websocket_rpc[websocket-client]
```

Then use websocket_client_handler_cls parameter:

```python
import asyncio
from fastapi_websocket_rpc import RpcMethodsBase, WebSocketRpcClient, ProxyEnabledWebSocketClientHandler

async def run_client(uri):
    async with WebSocketRpcClient(uri, RpcMethodsBase(), websocket_client_handler_cls = ProxyEnabledWebSocketClientHandler) as client:
```

Just set standard environment variables (lowercase and uppercase works): http_proxy, https_proxy, and no_proxy before running python script.


## Pull requests - welcome!
- Please include tests for new features 


