from enum import Enum
from typing import Dict, Generic, Optional, TypeVar

from pydantic import BaseModel

from .utils import is_pydantic_pre_v2

UUID = str


class RpcRequest(BaseModel):
    method: str
    arguments: Optional[Dict] = {}
    call_id: Optional[UUID] = None


ResponseT = TypeVar("ResponseT")


# Check pydantic version to handle deprecated GenericModel
if is_pydantic_pre_v2():
    from pydantic.generics import GenericModel

    class RpcResponse(GenericModel, Generic[ResponseT]):
        result: ResponseT
        result_type: Optional[str]
        call_id: Optional[UUID] = None

else:

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
