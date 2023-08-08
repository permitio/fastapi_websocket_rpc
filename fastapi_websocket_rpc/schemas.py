from typing import Dict, Generic, List, Optional, TypeVar
from enum import Enum

from pydantic.v1 import BaseModel

UUID = str


class RpcRequest(BaseModel):
    method: str
    arguments: Optional[Dict] = {}
    call_id: Optional[UUID] = None


ResponseT = TypeVar("ResponseT")


class RpcResponse(BaseModel, Generic[ResponseT]):
    result: ResponseT
    result_type: Optional[str]
    call_id: Optional[UUID] = None


class RpcMessage(BaseModel):
    request: Optional[RpcRequest] = None
    response: Optional[RpcResponse] = None


class WebSocketFrameType(str, Enum):
    Text = "text"
    Binary = "binary"
