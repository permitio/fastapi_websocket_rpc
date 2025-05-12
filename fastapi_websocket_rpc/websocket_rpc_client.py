import asyncio
import logging
from typing import Coroutine, Dict, List, Type

from tenacity import retry, RetryCallState, wait
from tenacity.retry import retry_if_exception

from .rpc_methods import PING_RESPONSE, RpcMethodsBase
from .rpc_channel import RpcChannel, OnConnectCallback, OnDisconnectCallback
from .logger import get_logger
from .simplewebsocket import SimpleWebSocket, JsonSerializingWebSocket

logger = get_logger("RPC_CLIENT")

try:
    import websockets
except ImportError:
    websockets = None

try:
    import websocket
except ImportError:
    # Websocket-client optional module is not installed.
    websocket = None

class ProxyEnabledWebSocketClientHandler(SimpleWebSocket):
    """
    Handler that use https://websocket-client.readthedocs.io/en/latest module.
    This implementation supports HTTP proxy, though HTTP_PROXY and HTTPS_PROXY environment variable.
    This is not documented, but in code, see https://github.com/websocket-client/websocket-client/blob/master/websocket/_url.py#L163
    The module is not written as coroutine: https://websocket-client.readthedocs.io/en/latest/threading.html#asyncio-library-usage, so 
    as a workaround, the send/recv are called in "run_in_executor" method.
    TODO: remove this implementation after https://github.com/python-websockets/websockets/issues/364 is fixed and use WebSocketsClientHandler instead.

    Note: the connect timeout, if not specified, is the default socket connect timeout, which could be around 2min, so a bit longer than WebSocketsClientHandler.
    """
    def __init__(self):
        if websocket is None:
            raise RuntimeError("Proxy handler requires websocket-client library")
        self._websocket = None

    """
    Args:
        **kwargs: Additional args passed to connect
            https://websocket-client.readthedocs.io/en/latest/examples.html#connection-options
            https://websocket-client.readthedocs.io/en/latest/core.html#websocket._core.WebSocket.connect
    """
    async def connect(self, uri: str, **connect_kwargs):
        try:
            self._websocket = await asyncio.get_event_loop().run_in_executor(None, websocket.create_connection, uri, **connect_kwargs)
        # See https://websocket-client.readthedocs.io/en/latest/exceptions.html
        except websocket._exceptions.WebSocketAddressException:
            logger.info("websocket address info cannot be found")
            raise
        except websocket._exceptions.WebSocketBadStatusException:
            logger.info("bad handshake status code")
            raise
        except websocket._exceptions.WebSocketConnectionClosedException:
            logger.info("remote host closed the connection or some network error happened")
            raise
        except websocket._exceptions.WebSocketPayloadException:
            logger.info(
                f"WebSocket payload is invalid")
            raise
        except websocket._exceptions.WebSocketProtocolException:
            logger.info(f"WebSocket protocol is invalid")
            raise
        except websocket._exceptions.WebSocketProxyException:
            logger.info(f"proxy error occurred")
            raise
        except OSError as err:
            logger.info("RPC Connection failed - %s", err)
            raise
        except Exception as err:
            logger.exception("RPC Error")
            raise

    async def send(self, msg):
        if self._websocket is None:
            # connect must be called before.
            logging.error("Websocket connect() must be called before.")
        await asyncio.get_event_loop().run_in_executor(None, self._websocket.send, msg)

    async def recv(self):
        if self._websocket is None:
            # connect must be called before.
            logging.error("Websocket connect() must be called before.")
        try:
            msg = await asyncio.get_event_loop().run_in_executor(None, self._websocket.recv)
        except websocket._exceptions.WebSocketConnectionClosedException as err:
            logger.debug("Connection closed.", exc_info=True)
            # websocket.WebSocketConnectionClosedException means remote host closed the connection or some network error happened
            # Returning None to ensure we get out of the loop, with no Exception.
            return None
        return msg

    async def close(self, code: int = 1000):
        if self._websocket is not None:
            # Case opened, we have something to close.
            await asyncio.get_event_loop().run_in_executor(None, self._websocket.close, code)

class WebSocketsClientHandler(SimpleWebSocket):
    """
    Handler that use https://websockets.readthedocs.io/en/stable module.
    This implementation does not support HTTP proxy (see https://github.com/python-websockets/websockets/issues/364).
    """
    def __init__(self):
        if websockets is None:
            raise RuntimeError("Default handler requires websockets library")
        self._websocket = None

    """
    Args:
        **kwargs: Additional args passed to connect
            https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html#opening-a-connection
    """
    async def connect(self, uri: str, **connect_kwargs):
        try:
            self._websocket = await websockets.connect(uri, **connect_kwargs)
        except ConnectionRefusedError:
            logger.info("RPC connection was refused by server")
            raise
        except websockets.ConnectionClosedError:
            logger.info("RPC connection lost")
            raise
        except websockets.ConnectionClosedOK:
            logger.info("RPC connection closed")
            raise
        except websockets.InvalidStatusCode as err:
            logger.info(
                f"RPC Websocket failed - with invalid status code {err.status_code}")
            raise
        except websockets.WebSocketException as err:
            logger.info(f"RPC Websocket failed - with {err}")
            raise
        except OSError as err:
            logger.info("RPC Connection failed - %s", err)
            raise
        except Exception as err:
            logger.exception("RPC Error")
            raise

    async def send(self, msg):
        if self._websocket is None:
            # connect must be called before.
            logging.error("Websocket connect() must be called before.")
        await self._websocket.send(msg)

    async def recv(self):
        if self._websocket is None:
            # connect must be called before.
            logging.error("Websocket connect() must be called before.")
        try:
            msg = await self._websocket.recv()
        except websockets.exceptions.ConnectionClosed:
            logger.debug("Connection closed.", exc_info=True)
            return None
        return msg

    async def close(self, code: int = 1000):
        if self._websocket is not None:
            # Case opened, we have something to close.
            await self._websocket.close(code)


def isNotForbbiden(value) -> bool:
    """
    Returns:
        bool: Returns True as long as the given exception value doesn't hold HTTP status codes 401 or 403
    """
    value = getattr(value, "response", value)  # `websockets.InvalidStatus` exception contains a status code inside the `response` property
    return not (hasattr(value, "status_code") and value.status_code in (401, 403))


class WebSocketRpcClient:
    """
    RPC-client to connect to an WebsocketRPCEndpoint
    Can call methods exposed by server
    Exposes methods that the server can call
    """

    def logerror(retry_state: RetryCallState):
        logger.exception(retry_state.outcome.exception())

    DEFAULT_RETRY_CONFIG = {
        'wait': wait.wait_random_exponential(min=0.1, max=120),
        'retry': retry_if_exception(isNotForbbiden),
        'reraise': True,
        "retry_error_callback": logerror
    }

    # RPC ping check on successful Websocket connection
    # @see wait_on_rpc_ready
    # interval to try RPC-pinging the sever (Seconds)
    WAIT_FOR_INITIAL_CONNECTION = 1
    # How many times to try re-pinging before rejecting the entire connection
    MAX_CONNECTION_ATTEMPTS = 5

    def __init__(self, uri: str, methods: RpcMethodsBase = None,
                 retry_config=None,
                 default_response_timeout: float = None,
                 on_connect: List[OnConnectCallback] = None,
                 on_disconnect: List[OnDisconnectCallback] = None,
                 keep_alive: float = 0,
                 serializing_socket_cls: Type[SimpleWebSocket] = JsonSerializingWebSocket,
                 websocket_client_handler_cls: Type[SimpleWebSocket] = WebSocketsClientHandler,
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

            **kwargs: Additional args passed to connect, depends on websocket_client_handler_cls


            usage:
                async with  WebSocketRpcClient(uri, RpcUtilityMethods()) as client:
                response = await client.call("echo", {'text': "Hello World!"})
                print (response)
        """
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
        self.retry_config = retry_config if retry_config is not None else self.DEFAULT_RETRY_CONFIG
        # Event handlers
        self._on_disconnect = on_disconnect
        self._on_connect = on_connect
        # serialization
        self._serializing_socket_cls = serializing_socket_cls
        # websocket client implementation
        self._websocket_client_handler_cls = websocket_client_handler_cls

    async def __connect__(self):
        logger.info(f"Trying server - {self.uri}")
        try:
            raw_ws = self._websocket_client_handler_cls()
            # Wrap socket in our serialization class
            self.ws = self._serializing_socket_cls(raw_ws)
        except:
            logger.exception("Class instantiation error.")
            raise
        # No try/catch for connect() to avoid double error logging. Any exception from the method must be handled by
        # itself for logging, then raised and caught outside of connect() (e.g.: for retry purpose).
        # Start connection 
        await self.ws.connect(self.uri, **self.connect_kwargs)
        try:
            try:
                # Init an RPC channel to work on-top of the connection
                self.channel = RpcChannel(
                    self.methods, self.ws, default_response_timeout=self.default_response_timeout)
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
            except:
                # Clean partly initiated state on error
                if self.ws is not None:
                    await self.ws.close()
                if self.channel is not None:
                    await self.channel.close()
                self.cancel_tasks()
                raise
        except Exception as err:
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
        logger.info("Closing RPC client")
        # Close underlying connection
        if self.ws is not None:
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
        """
        Read responses from socket worker
        """
        try:
            while True:
                raw_message = await self.ws.recv()
                if raw_message is None:
                    # None is a special case where connection is closed.
                    logger.info("Connection was terminated.")
                    await self.close()
                    break
                else:
                    await self.channel.on_message(raw_message)
        # Graceful external termination options
        # task was canceled
        except asyncio.CancelledError:
            pass
        except Exception as err:
            logger.exception("RPC Reader task failed")
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
        while received_response is None and attempt_count < self.MAX_CONNECTION_ATTEMPTS:
            try:
                received_response = await asyncio.wait_for(self.ping(), self.WAIT_FOR_INITIAL_CONNECTION)
            except asyncio.exceptions.TimeoutError:
                attempt_count += 1

    async def ping(self):
        logger.debug("Pinging server")
        answer = await self.channel.other._ping_()
        return answer

    def _cancel_keep_alive_task(self):
        if self._keep_alive_task is not None:
            logger.debug("Cancelling keep alive task")
            self._keep_alive_task.cancel()
            self._keep_alive_task = None

    def _start_keep_alive_task(self):
        if self._keep_alive_interval > 0:
            logger.debug(
                f"Starting keep alive task interval='{self._keep_alive_interval}' seconds")
            self._keep_alive_task = asyncio.create_task(self._keep_alive())

    async def wait_on_reader(self):
        """
        Join on the internal reader task
        """
        try:
            await self._read_task
        except asyncio.CancelledError:
            logger.info(f"RPC Reader task was cancelled.")

    async def call(self, name, args={}, timeout=None):
        """
        Call a method and wait for a response to be received
         Args:
            name (str): name of the method to call on the other side (As defined on the otherside's RpcMethods object)
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
