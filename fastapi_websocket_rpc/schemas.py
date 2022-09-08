from typing import Dict, Generic, List, Optional, TypeVar
from enum import Enum

from pydantic import BaseModel
from pydantic.generics import GenericModel

UUID = str


class RpcRequest(BaseModel):
    method: str
    arguments: Optional[Dict] = {}
    call_id: Optional[UUID] = None


ResponseT = TypeVar('ResponseT')


class RpcResponse(GenericModel, Generic[ResponseT]):
    result: ResponseT
    result_type: Optional[str]
    call_id: Optional[UUID] = None


class RpcMessage(BaseModel):
    request: Optional[RpcRequest] = None
    response: Optional[RpcResponse] = None


class WebSocketFrameType(str, Enum):
    Text = "text"
    Binary = "binary"
