import asyncio
from contextlib import suppress
from typing import Dict, List, Type

import tenacity
import websockets
from tenacity import retry, wait
from tenacity.retry import retry_if_exception
from websockets.exceptions import (
    ConnectionClosedError,
    ConnectionClosedOK,
    InvalidStatusCode,
    WebSocketException,
)

from .logger import get_logger
from .rpc_channel import OnConnectCallback, OnDisconnectCallback, RpcChannel
from .rpc_methods import PING_RESPONSE, RpcMethodsBase
from .simplewebsocket import JsonSerializingWebSocket, SimpleWebSocket

logger = get_logger("RPC_CLIENT")


def isNotInvalidStatusCode(value):
    return not isinstance(value, InvalidStatusCode)


def isNotForbbiden(value) -> bool:
    """
    Returns:
        bool: Returns True as long as the given exception value is not
        InvalidStatusCode with 401 or 403
    """
    return not (
        isinstance(value, InvalidStatusCode)
        and (value.status_code == 401 or value.status_code == 403)
    )


class WebSocketRpcClient:
    """
    RPC-client to connect to an WebsocketRPCEndpoint
    Can call methods exposed by server
    Exposes methods that the server can call
    """

    def logerror(retry_state: tenacity.RetryCallState):
        logger.exception(retry_state.outcome.exception())

    DEFAULT_RETRY_CONFIG = {
        "wait": wait.wait_random_exponential(min=0.1, max=120),
        "retry": retry_if_exception(isNotForbbiden),
        "reraise": True,
        "retry_error_callback": logerror,
    }

    # RPC ping check on successful Websocket connection
    # @see wait_on_rpc_ready
    # interval to try RPC-pinging the sever (Seconds)
    WAIT_FOR_INITIAL_CONNECTION = 1
    # How many times to try re-pinging before rejecting the entire connection
    MAX_CONNECTION_ATTEMPTS = 5

    def __init__(
        self,
        uri: str,
        methods: RpcMethodsBase = None,
        retry_config=None,
        default_response_timeout: float = None,
        on_connect: List[OnConnectCallback] = None,
        on_disconnect: List[OnDisconnectCallback] = None,
        keep_alive: float = 0,
        serializing_socket_cls: Type[SimpleWebSocket] = JsonSerializingWebSocket,
        **kwargs,
    ):
        """
        Args:
            uri (str): server uri to connect to (e.g. 'http://localhost/ws/client1')
            methods (RpcMethodsBase): RPC methods to expose to the server
            retry_config (dict): Tenacity.retry config
            (@see https://tenacity.readthedocs.io/en/latest/api.html#retry-main-api)
            default_response_timeout (float): default time in seconds
            on_connect (List[Coroutine]): callbacks on connection being established
            (each callback is called with the channel)
            @note exceptions thrown in on_connect callbacks propagate to the client
            and will cause connection restart!
            on_disconnect (List[Coroutine]): callbacks on connection termination
            (each callback is called with the channel)
            keep_alive(float): interval in seconds to send a keep-alive ping,
            Defaults to 0, which means keep alive is disabled.

            **kwargs: Additional args passed to connect (@see class Connect at
            websockets/client.py)
            https://websockets.readthedocs.io/en/stable/api.html#websockets.client.connect


            usage:
                async with  WebSocketRpcClient(uri, RpcUtilityMethods()) as client:
                response = await client.call("echo", {'text': "Hello World!"})
                print (response)
        """  # noqa: E501
        self.methods = methods or RpcMethodsBase()
        self.connect_kwargs = kwargs
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
        self.retry_config = (
            retry_config if retry_config is not None else self.DEFAULT_RETRY_CONFIG
        )
        # Event handlers
        self._on_disconnect = on_disconnect
        self._on_connect = on_connect
        # serialization
        self._serializing_socket_cls = serializing_socket_cls

    async def __connect__(self):
        try:
            try:
                logger.info(f"Connecting to {self.uri}...")
                # Create a WebSocket connection.
                logger.debug(
                    f"Creating a WebSocket connection to {self.uri} with parameters: {self.connect_kwargs}..."  # noqa: E501
                )
                raw_ws = await websockets.connect(self.uri, **self.connect_kwargs)
                # Wrap the WebSocket connection with a wrapper for serializing
                # and deserializing messages.
                logger.debug(
                    f"Wrapping WebSocket connection with {self._serializing_socket_cls.__name__}..."  # noqa: E501
                )
                self.ws = self._serializing_socket_cls(raw_ws)
                # Initialize an RPC channel to work on top of the connection.
                self.channel = RpcChannel(
                    self.methods,
                    self.ws,
                    default_response_timeout=self.default_response_timeout,
                )
                # Register handlers.
                self.channel.register_connect_handler(self._on_connect)
                self.channel.register_disconnect_handler(self._on_disconnect)
                # Start reading incoming RPC calls.
                self._read_task = asyncio.create_task(self.reader())
                # Start keep alive (if enabled, i.e., value isn't 0).
                self._start_keep_alive_task()
                # Wait for RPC channel on the server to be ready (ping check).
                await self.wait_on_rpc_ready()
                # Trigger connect signal handlers.
                await self.channel.on_connect()
                return self
            except:
                # Clean partly initiated state on error.
                if self.ws is not None:
                    await self.ws.close()
                if self.channel is not None:
                    await self.channel.close()
                self.cancel_tasks()
                raise
        except ConnectionRefusedError:
            logger.info("RPC connection was refused by server")
            raise
        except ConnectionClosedError:
            logger.info("RPC connection lost")
            raise
        except ConnectionClosedOK:
            logger.info("RPC connection closed")
            raise
        except InvalidStatusCode as err:
            logger.info(
                f"RPC Websocket failed - with invalid status code {err.status_code}"
            )
            raise
        except WebSocketException as err:
            logger.info(f"RPC Websocket failed - with {err}")
            raise
        except OSError as err:
            logger.info("RPC Connection failed - %s", err)
            raise
        except Exception:
            logger.exception("RPC Error")
            raise

    async def __aenter__(self):
        if self.retry_config is False:
            return await self.__connect__()
        else:
            return await retry(**self.retry_config)(self.__connect__)()

    async def __aexit__(self, *args, **kwargs):
        await self.close()

    async def close(self):
        logger.info("Closing RPC client...")
        # Close underlying connection
        if self.ws is not None:
            with suppress(RuntimeError):
                await self.ws.close()
        # Notify callbacks (but just once)
        if not self.channel.isClosed():
            # notify handlers (if any)
            await self.channel.on_disconnect()
            await self.channel.close()
        # Clear tasks
        self.cancel_tasks()

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
        """Read responses from socket worker."""
        try:
            while True:
                raw_message = await self.ws.recv()
                logger.debug(f"Received raw message: {raw_message}")
                await self.channel.on_message(raw_message)
        # Graceful external termination options
        # task was canceled
        except asyncio.CancelledError:
            logger.info("RPC read task was cancelled.")
            pass
        except websockets.exceptions.ConnectionClosed:
            logger.info("Connection was terminated.")
            await self.close()
        except:
            logger.exception("RPC reader task failed.")
            raise

    async def _keep_alive(self):
        try:
            while True:
                await asyncio.sleep(self._keep_alive_interval)
                answer = await self.ping()
                assert answer.result == PING_RESPONSE
        # Graceful external termination options
        # task was canceled
        except asyncio.CancelledError:
            pass

    async def wait_on_rpc_ready(self):
        received_response = None
        attempt_count = 0
        while (
            received_response is None and attempt_count < self.MAX_CONNECTION_ATTEMPTS
        ):
            try:
                received_response = await asyncio.wait_for(
                    self.ping(), self.WAIT_FOR_INITIAL_CONNECTION
                )
            except asyncio.exceptions.TimeoutError:
                attempt_count += 1

    async def ping(self):
        logger.debug("Pinging server...")
        answer = await self.channel.other._ping_()
        logger.debug(f"Got ping response: {answer}")
        return answer

    def _cancel_keep_alive_task(self):
        if self._keep_alive_task is not None:
            logger.debug("Cancelling keep alive task")
            self._keep_alive_task.cancel()
            self._keep_alive_task = None

    def _start_keep_alive_task(self):
        if self._keep_alive_interval > 0:
            logger.debug(
                f"Starting keep alive task interval='{self._keep_alive_interval}' seconds"  # noqa: E501
            )
            self._keep_alive_task = asyncio.create_task(self._keep_alive())
        else:
            logger.debug('"Keep alive" is disabled')

    async def wait_on_reader(self):
        """
        Join on the internal reader task
        """
        try:
            await self._read_task
        except asyncio.CancelledError:
            logger.info("RPC Reader task was cancelled.")

    async def call(self, name, args={}, timeout=None):
        """
        Call a method and wait for a response to be received
         Args:
            name (str): name of the method to call on the other side (As defined on
            the otherside's RpcMethods object)
            args (dict): keyword arguments to be passed to otherside method
            timeout (float, optional): See RpcChannel.
        """
        return await self.channel.call(name, args, timeout=timeout)

    @property
    def other(self):
        """
        Proxy object to call methods on the other side
        """
        return self.channel.other
