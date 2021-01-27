import asyncio
import os
import sys
import typing
import copy

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .connection_manager import ConnectionManager
from .schemas import RpcRequest, RpcResponse
from .utils import gen_uid


# NULL default value - indicating no response was received
class NoResponse:
    pass


class RpcMethodsBase:
    """
    The basic interface RPC channels excpets method groups to implement.
     - create copy of the method object
     - set channel 
    """

    def __init__(self):
        self._channel = None

    def set_channel(self, channel):
        """
        Allows the channel to share access to its functions to the methods once nested under it
        """
        self._channel = channel

    @property
    def channel(self):
        return self._channel

    def copy(self):
        """ Simple copy ctor - overriding classes may need to override copy as well."""
        return copy.copy(self)


class ProcessDetails(BaseModel):
    pid: int = os.getpid()
    cmd: typing.List[str] = sys.argv
    workingdir: str = os.getcwd()


class RpcUtilityMethods(RpcMethodsBase):
    """
    A simple set of RPC functions useful for management and testing
    """

    def __init__(self):
        """
        endpoint (WebsocketRPCEndpoint): the endpoint these methods are loaded into
        """
        super().__init__()

    async def get_proccess_details(self) -> ProcessDetails:
        return ProcessDetails()

    async def call_me_back(self, method_name="", args={}) -> str:
        if self.channel is not None:
            # generate a uid we can use to track this request
            call_id = gen_uid()
            # Call async -  without waiting to avoid locking the event_loop
            asyncio.create_task(self.channel.async_call(method_name, args=args, call_id=call_id))
            # return the id- which can be used to check the response once it's received 
            return call_id

    async def get_response(self, call_id="") -> typing.Any:
        if self.channel is not None:
            res = self.channel.get_saved_response(call_id)
            self.channel.clear_saved_call(call_id)
            return res
            
    async def echo(self, text: str) -> str:
        return text
