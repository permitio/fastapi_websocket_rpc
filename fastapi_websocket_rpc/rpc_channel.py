"""
Definition for an RPC channel protocol on top of a websocket - enabling bi-directional request/response interactions
"""
import asyncio
from inspect import _empty, getmembers, ismethod, signature
from typing import Any, Dict, List

from pydantic import ValidationError

from .logger import get_logger
from .rpc_methods import EXPOSED_BUILT_IN_METHODS, NoResponse, RpcMethodsBase
from .schemas import RpcMessage, RpcRequest, RpcResponse
from .utils import gen_uid, pydantic_parse

logger = get_logger("RPC_CHANNEL")


class DEFAULT_TIMEOUT:
    pass


class RemoteValueError(ValueError):
    pass


class RpcException(Exception):
    pass


class RpcChannelClosedException(Exception):
    """
    Raised when the channel is closed mid-operation
    """

    pass


class UnknownMethodException(RpcException):
    pass


class RpcPromise:
    """
    Simple Event and id wrapper/proxy
    Holds the state of a pending request
    """

    def __init__(self, request: RpcRequest):
        self._request = request
        self._id = request.call_id
        # event used to wait for the completion of the request (upon receiving its matching response)
        self._event = asyncio.Event()

    @property
    def request(self):
        return self._request

    @property
    def call_id(self):
        return self._id

    def set(self):
        """
        Signal completion of request with received response
        """
        self._event.set()

    def wait(self):
        """
        Wait on the internal event - triggered on response
        """
        return self._event.wait()


class RpcProxy:
    """
    Helper class
    provide a __call__ interface for an RPC method over a given channel
    """

    def __init__(self, channel, method_name) -> None:
        self.method_name = method_name
        self.channel = channel

    def __call__(self, **kwds: Any) -> Any:
        return self.channel.call(self.method_name, args=kwds)


class RpcCaller:
    """
    Helper class provide an object (aka other) with callable methods for each remote method on the otherside
    """

    def __init__(self, channel, methods=None) -> None:
        self._channel = channel
        self._method_names = (
            [method[0] for method in getmembers(methods, lambda i: ismethod(i))]
            if methods is not None
            else None
        )

    def __getattribute__(self, name: str):
        if (not name.startswith("_") or name in EXPOSED_BUILT_IN_METHODS) and (
            self._method_names is None or name in self._method_names
        ):
            return RpcProxy(self._channel, name)
        else:
            return super().__getattribute__(name)


# Callback signatures
async def OnConnectCallback(channel):
    pass


async def OnDisconnectCallback(channel):
    pass


async def OnErrorCallback(channel, err: Exception):
    pass


class RpcChannel:
    """
    A wire agnostic json-rpc channel protocol for both server and client.
    Enable each side to send RPC-requests (calling exposed methods on other side) and receive rpc-responses with the return value

    provides a .other property for calling remote methods.
    e.g. answer = channel.other.add(a=1,b=1) will (For example) ask the other side to perform 1+1 and will return an RPC-response of 2
    """

    def __init__(
        self,
        methods: RpcMethodsBase,
        socket,
        channel_id=None,
        default_response_timeout=None,
        sync_channel_id=False,
        **kwargs,
    ):
        """

        Args:
            methods (RpcMethodsBase): RPC methods to expose to other side
            socket: socket object providing simple send/recv methods
            channel_id (str, optional): uuid for channel. Defaults to None in which case a random UUID is generated.
            default_response_timeout(float, optional) default timeout for RPC call responses. Defaults to None - i.e. no timeout
            sync_channel_id(bool, optional) should get the other side of the channel id, helps to identify connections, cost a bit networking time.
                Defaults to False - i.e. not getting the other side channel id
        """
        self.methods = methods._copy_()
        # allow methods to access channel (for recursive calls - e.g. call me as a response for me calling you)
        self.methods._set_channel_(self)
        # Pending requests - id-mapped to async-event
        self.requests: Dict[str, asyncio.Event] = {}
        # Received responses
        self.responses = {}
        self.socket = socket
        # timeout
        self.default_response_timeout = default_response_timeout
        # Unique channel id
        self.id = channel_id if channel_id is not None else gen_uid()
        # flag control should we retrieve the channel id of the other side
        self._sync_channel_id = sync_channel_id
        # The channel id of the other side (if sync_channel_id is True)
        self._other_channel_id = None
        # asyncio event to check if we got the channel id of the other side
        self._channel_id_synced = asyncio.Event()
        #
        # convenience caller
        # TODO - pass remote methods object to support validation before call
        self.other = RpcCaller(self)
        # core event callback registers
        self._connect_handlers: List[OnConnectCallback] = []
        self._disconnect_handlers: List[OnDisconnectCallback] = []
        self._error_handlers = []
        # internal event
        self._closed = asyncio.Event()

        # any other kwarg goes straight to channel context (Accessible to methods)
        self._context = kwargs or {}

    @property
    def context(self) -> Dict[str, Any]:
        return self._context

    async def get_other_channel_id(self) -> str:
        """
        Method to get the channel id of the other side of the channel
        The _channel_id_synced verify we have it
        Timeout exception can be raised if the value isn't available
        """
        await asyncio.wait_for(
            self._channel_id_synced.wait(), self.default_response_timeout
        )
        return self._other_channel_id

    def get_return_type(self, method):
        method_signature = signature(method)
        return (
            method_signature.return_annotation
            if method_signature.return_annotation is not _empty
            else str
        )

    async def send(self, data):
        """
        For internal use. wrap calls to underlying socket
        """
        await self.socket.send(data)

    async def receive(self):
        """
        For internal use. wrap calls to underlying socket
        """
        return await self.socket.recv()

    async def close(self):
        res = await self.socket.close()
        # signal closer
        self._closed.set()
        return res

    def isClosed(self):
        return self._closed.is_set()

    async def wait_until_closed(self):
        """
        Waits until the close internal event happens.
        """
        return await self._closed.wait()

    async def on_message(self, data):
        """
        Handle an incoming RPC message
        This is the main function servers/clients using the channel need to call (upon reading a message on the wire)
        """
        try:
            message = pydantic_parse(RpcMessage, data)
            if message.request is not None:
                await self.on_request(message.request)
            if message.response is not None:
                await self.on_response(message.response)
        except ValidationError as e:
            logger.error(f"Failed to parse message", {"message": data, "error": e})
            await self.on_error(e)
        except Exception as e:
            await self.on_error(e)
            raise

    def register_connect_handler(self, coros: List[OnConnectCallback] = None):
        """
        Register a connection handler callback that will be called (As an async task)) with the channel
        Args:
            coros (List[Coroutine]): async callback
        """
        if coros is not None:
            self._connect_handlers.extend(coros)

    def register_disconnect_handler(self, coros: List[OnDisconnectCallback] = None):
        """
        Register a disconnect handler callback that will be called (As an async task)) with the channel id
        Args:
            coros (List[Coroutine]): async callback
        """
        if coros is not None:
            self._disconnect_handlers.extend(coros)

    def register_error_handler(self, coros: List[OnErrorCallback] = None):
        """
        Register an error handler callback that will be called (As an async task)) with the channel and triggered error.
        Args:
            coros (List[Coroutine]): async callback
        """
        if coros is not None:
            self._error_handlers.extend(coros)

    async def on_handler_event(self, handlers, *args, **kwargs):
        await asyncio.gather(*(callback(*args, **kwargs) for callback in handlers))

    async def on_connect(self):
        """
        Run get other channel id if sync_channel_id is True
        Run all callbacks from self._connect_handlers
        """
        if self._sync_channel_id:
            self._get_other_channel_id_task = asyncio.create_task(
                self._get_other_channel_id()
            )
        await self.on_handler_event(self._connect_handlers, self)

    async def _get_other_channel_id(self):
        """
        Perform call to the other side of the channel to get its channel id
        Each side is generating the channel id by itself so there is no way to identify a connection without this sync
        """
        if self._other_channel_id is None:
            other_channel_id = await self.other._get_channel_id_()
            self._other_channel_id = (
                other_channel_id.result
                if other_channel_id and other_channel_id.result
                else None
            )
            if self._other_channel_id is None:
                raise RemoteValueError()
            # update asyncio event that we received remote channel id
            self._channel_id_synced.set()
            return self._other_channel_id
        else:
            return self._other_channel_id

    async def on_disconnect(self):
        # disconnect happened - mark the channel as closed
        self._closed.set()
        await self.on_handler_event(self._disconnect_handlers, self)

    async def on_error(self, error: Exception):
        await self.on_handler_event(self._error_handlers, self, error)

    async def on_request(self, message: RpcRequest):
        """
        Handle incoming RPC requests - calling relevant exposed method
        Note: methods prefixed with "_" are protected and ignored.

        Args:
            message (RpcRequest): the RPC request with the method to call
        """
        # TODO add exception support (catch exceptions and pass to other side as response with errors)
        logger.debug(
            "Handling RPC request - %s", {"request": message, "channel": self.id}
        )
        method_name = message.method
        # Ignore "_" prefixed methods (except the built in "_ping_")
        if isinstance(method_name, str) and (
            not method_name.startswith("_") or method_name in EXPOSED_BUILT_IN_METHODS
        ):
            method = getattr(self.methods, method_name)
            if callable(method):
                result = await method(**message.arguments)
                if result is not NoResponse:
                    # get indicated type
                    result_type = self.get_return_type(method)
                    # if no type given - try to convert to string
                    if result_type is str and type(result) is not str:
                        result = str(result)
                    response = RpcMessage(
                        response=RpcResponse[result_type](
                            call_id=message.call_id,
                            result=result,
                            result_type=getattr(
                                result_type,
                                "__name__",
                                getattr(result_type, "_name", "unknown-type"),
                            ),
                        )
                    )
                    await self.send(response)

    def get_saved_promise(self, call_id):
        return self.requests[call_id]

    def get_saved_response(self, call_id):
        return self.responses[call_id]

    def clear_saved_call(self, call_id):
        del self.requests[call_id]
        del self.responses[call_id]

    async def on_response(self, response: RpcResponse):
        """
        Handle an incoming response to a previous RPC call

        Args:
            response (RpcResponse): the received response
        """
        logger.debug("Handling RPC response - %s", {"response": response})
        if response.call_id is not None and response.call_id in self.requests:
            self.responses[response.call_id] = response
            promise = self.requests[response.call_id]
            promise.set()

    async def wait_for_response(self, promise, timeout=DEFAULT_TIMEOUT) -> RpcResponse:
        """
        Wait on a previously made call
        Args:
            promise (RpcPromise): the awaitable-wrapper returned from the RPC request call
            timeout (float, None, or DEFAULT_TIMEOUT): the timeout to wait on the response, defaults to DEFAULT_TIMEOUT.
                - DEFAULT_TIMEOUT - use the value passed as 'default_response_timeout' in channel init
                - None - no timeout
                - a number - seconds to wait before timing out
        Raises:
            asyncio.exceptions.TimeoutError - on timeout
            RpcChannelClosedException - if the channel fails before wait could be completed
        """
        if timeout is DEFAULT_TIMEOUT:
            timeout = self.default_response_timeout
        # wait for the promise or until the channel is terminated
        _, pending = await asyncio.wait(
            [
                asyncio.ensure_future(promise.wait()),
                asyncio.ensure_future(self._closed.wait()),
            ],
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        # Cancel all pending futures and then detect if close was the first done
        for fut in pending:
            fut.cancel()
        response = self.responses.get(promise.call_id, NoResponse)
        # if the channel was closed before we could finish
        if response is NoResponse:
            raise RpcChannelClosedException(
                f"Channel Closed before RPC response for {promise.call_id} could be received"
            )
        self.clear_saved_call(promise.call_id)
        return response

    async def async_call(self, name, args={}, call_id=None) -> RpcPromise:
        """
        Call a method and return the event and the sent message (including the chosen call_id)
        use self.wait_for_response on the event and call_id to get the return value of the call
        Args:
            name (str): name of the method to call on the other side
            args (dict): keyword args to pass tot he other side
            call_id (string, optional): a UUID to use to track the call () - override only with true UUIDs
        """
        call_id = call_id or gen_uid()
        msg = RpcMessage(
            request=RpcRequest(method=name, arguments=args, call_id=call_id)
        )
        logger.debug("Calling RPC method - %s", {"message": msg})
        await self.send(msg)
        promise = self.requests[msg.request.call_id] = RpcPromise(msg.request)
        return promise

    async def call(self, name, args={}, timeout=DEFAULT_TIMEOUT):
        """
        Call a method and wait for a response to be received
        """
        promise = await self.async_call(name, args)
        return await self.wait_for_response(promise, timeout=timeout)
