from pydantic import BaseModel


class GatewaySyncResponse(BaseModel):
    ok: bool
    message: str
