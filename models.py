from pydantic import BaseModel


class ScanData(BaseModel):
    robot_id: str
    image: str
    analysis: dict
    timestamp: str


class CommandData(BaseModel):
    robot_id: str
    command: str
    reason: str = "manual"
