from enum import Enum
from typing import Dict, Generic, Optional, TypeVar

import pydantic
from packaging import version
from pydantic import BaseModel

UUID = str


class RpcRequest(BaseModel):
    method: str
    arguments: Optional[Dict] = {}
    call_id: Optional[UUID] = None


ResponseT = TypeVar("ResponseT")


# Check pydantic version to handle deprecated GenericModel
if version.parse(pydantic.VERSION) < version.parse("2.0.0"):
    from pydantic.generics import GenericModel

    class RpcResponse(GenericModel, Generic[ResponseT]):
        result: ResponseT
        result_type: Optional[str]

else:

    class RpcResponse(BaseModel, Generic[ResponseT]):
        result: ResponseT
        result_type: Optional[str]


class RpcMessage(BaseModel):
    request: Optional[RpcRequest] = None
    response: Optional[RpcResponse] = None


class WebSocketFrameType(str, Enum):
    Text = "text"
    Binary = "binary"
