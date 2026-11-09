from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field

class ScreenEventCreate(BaseModel):
    device_id: str = Field(..., min_length=3, max_length=100, description="Identificador único del dispositivo")
    model_name: Optional[str] = Field("Android Device", max_length=100)
    screen_on_at: datetime = Field(..., description="Fecha y hora cuando la pantalla se encendió")
    screen_off_at: datetime = Field(..., description="Fecha y hora cuando la pantalla se apagó")
    duration_seconds: float = Field(..., ge=0, le=86400, description="Duración en segundos")

class ScreenLogResponse(BaseModel):
    id: int
    device_id: str
    screen_on_at: datetime
    screen_off_at: datetime
    duration_seconds: float
    created_at: datetime

    class Config:
        from_attributes = True

class DeviceSummary(BaseModel):
    id: str
    model_name: str
    total_screen_time_seconds: float
    total_screen_time_formatted: str
    total_unlocks: int
    last_seen: datetime

    class Config:
        from_attributes = True
