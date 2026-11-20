from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str = Field(serialization_alias="request_id")


class MessageResponse(BaseModel):
    message: str