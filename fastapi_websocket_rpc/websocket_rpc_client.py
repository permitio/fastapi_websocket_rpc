import asyncio
from typing import Coroutine, Dict, List
from tenacity import retry, wait
from tenacity.retry import retry_if_exception

import websockets
from websockets.exceptions import InvalidStatusCode

from .rpc_methods import PING_RESPONSE, RpcMethodsBase
from .rpc_channel import RpcChannel
from .logger import get_logger

logger = get_logger("RPC_CLIENT")


def isNotInvalidStatusCode(value):
    return not isinstance(value, InvalidStatusCode)


class WebSocketRpcClient:
    """
    RPC-client to connect to an WebsocketRPCEndpoint
    Can call methodes exposed by server
    Exposes methods that the server can call
    """

    DEFAULT_RETRY_CONFIG = {
        'wait': wait.wait_random_exponential(),
        'retry': retry_if_exception(isNotInvalidStatusCode),
        'reraise': True
    }

    # RPC ping check on successful Websocket connection
    # @see wait_on_rpc_ready
    # interval to try RPC-pinging the sever (Seconds)
    WAIT_FOR_INITIAL_CONNECTION = 1
    # How many times to try repinging before rejecting the entire connection
    MAX_CONNECTION_ATTEMPTS = 5

    def __init__(self, uri: str, methods: RpcMethodsBase = None,
                 retry_config=None,
                 default_response_timeout: float = None,
                 on_connect: List[Coroutine] = None,
                 on_disconnect: List[Coroutine] = None,
                 keep_alive: float = 0,
                 **kwargs):
        """
        Args:
            uri (str): server uri to connect to (e.g. 'http://localhost/ws/client1')
            methods (RpcMethodsBase): RPC methods to expose to the server
            retry_config (dict): Tenacity.retry config (@see https://tenacity.readthedocs.io/en/latest/api.html#retry-main-api) 
            default_response_timeout (float): default time in seconds
            on_connect (List[Coroutine]): callbacks on connection being established (each callback is called with the channel)
                                          @note exceptions thrown in on_connect callbacks propagate to the client and will cause connection restart!
            on_disconnect (List[Coroutine]): callbacks on connection termination (each callback is called with the channel)
            keep_alive(float): interval in seconds to send a keep-alive ping, Defaults to 0, which means keep alive is disabled.

            **kwargs: Additional args passed to connect (@see class Connect at websockets/client.py)
                      https://websockets.readthedocs.io/en/stable/api.html#websockets.client.connect


            usage:
                async with  WebSocketRpcClient(uri, RpcUtilityMethods()) as client:
                response = await client.call("echo", {'text': "Hello World!"})
                print (response)
        """
        self.methods = methods or RpcMethodsBase()
        self.connect_kwargs = kwargs
        # Websocket connection
        self.conn = None
        # Websocket object
        self.ws = None
        # URI to connect on
        self.uri = uri
        # Pending requests - id mapped to async-event
        self.requests: Dict[str, asyncio.Event] = {}
        # Received responses
        self.responses = {}
        # Read worker
        self._read_task = None
        # Keep alive (Ping/Pong) task
        self._keep_alive_task = None
        self._keep_alive_interval = keep_alive
        # defaults
        self.default_response_timeout = default_response_timeout
        # RPC channel
        self.channel = None
        self.retry_config = retry_config if retry_config is not None else self.DEFAULT_RETRY_CONFIG
        # Event handlers
        self._on_disconnect = on_disconnect
        self._on_connect = on_connect

    async def __connect__(self):
        # Make sure we don't have any hanging tasks (from previous retry runs)
        self.cancel_tasks()
        logger.info("Trying server", uri=self.uri)
        # Start connection
        self.conn = websockets.connect(self.uri, **self.connect_kwargs)
        # Get socket
        self.ws = await self.conn.__aenter__()
        # Init an RPC channel to work on-top of the connection
        self.channel = RpcChannel(self.methods, self.ws, default_response_timeout=self.default_response_timeout)
        # register handlers
        self.channel.register_connect_handler(self._on_connect)
        self.channel.register_disconnect_handler(self._on_disconnect)
        # Start reading incoming RPC calls
        self._read_task = asyncio.create_task(self.reader())
        # start keep alive (if enabled i.e. value isn't 0)
        self._start_keep_alive_task()
        # Wait for RPC channel on the server to be ready (ping check)
        await self.wait_on_rpc_ready()
        # trigger connect handlers
        await self.channel.on_connect()
        return self

    async def __aenter__(self):
        if self.retry_config is False:
            return await self.__connect__()
        else:
            return await retry(**self.retry_config)(self.__connect__)()

    async def __aexit__(self, *args, **kwargs):
        # notify handlers (if any)
        await self.channel.on_disconnect()
        # Clear tasks
        self.cancel_tasks()
        # Stop socket
        if (hasattr(self.conn, "ws_client")):
            await self.conn.__aexit__(*args, **kwargs)

    def cancel_tasks(self):
        # Stop keep alive if enabled
        self._cancel_keep_alive_task()
        # Stop reader - if created
        self.cancel_reader_task()

    def cancel_reader_task(self):
        if self._read_task is not None:
            self._read_task.cancel()
            self._read_task = None

    async def reader(self):
        """
        Read responses from socket worker
        """
        while True:
            raw_message = await self.ws.recv()
            await self.channel.on_message(raw_message)

    async def _keep_alive(self):
        while True:
            await asyncio.sleep(self._keep_alive_interval)
            answer = await self.ping()
            assert answer.result == PING_RESPONSE

    async def wait_on_rpc_ready(self):
        received_response = None
        attempt_count = 0
        while received_response is None and attempt_count < self.MAX_CONNECTION_ATTEMPTS:
            try:
                received_response = await asyncio.wait_for(self.ping(), self.WAIT_FOR_INITIAL_CONNECTION)
            except TimeoutError:
                attempt_count += 1

    async def ping(self):
        logger.info("Pinging server")
        answer = await self.channel.other._ping_()
        return answer

    def _cancel_keep_alive_task(self):
        if self._keep_alive_task is not None:
            logger.info("Cancelling keep alive task")
            self._keep_alive_task.cancel()
            self._keep_alive_task = None

    def _start_keep_alive_task(self):
        if self._keep_alive_interval > 0:
            logger.info("Starting keep alive task", interval=f"{self._keep_alive_interval} seconds")
            self._keep_alive_task = asyncio.create_task(self._keep_alive())

    async def wait_on_reader(self):
        """
        Join on the internal reader task
        """
        await self._read_task

    async def call(self, name, args={}, timeout=None):
        """
        Call a method and wait for a response to be received
         Args: 
            name (str): name of the method to call on the other side (As defined on the otherside's RpcMethods object)
            args (dict): keyword arguments to be passeds to otherside method
        """
        return await self.channel.call(name, args, timeout=timeout)

    @property
    def other(self):
        """
        Proxy object to call methods on the other side
        """
        return self.channel.other
