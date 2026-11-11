from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Boolean
from sqlalchemy.orm import relationship
from database import Base

class Device(Base):
    __tablename__ = "devices"

    id = Column(String(100), primary_key=True, index=True) # Unique device UUID or Android ID
    model_name = Column(String(100), default="Android Device")
    is_screen_on = Column(Boolean, default=False) # Si la pantalla está encendida en este instante
    current_session_started_at = Column(DateTime, nullable=True) # Momento en que se encendió
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)

    logs = relationship("ScreenLog", back_populates="device", cascade="all, delete-orphan")


class ScreenLog(Base):
    __tablename__ = "screen_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    device_id = Column(String(100), ForeignKey("devices.id"), nullable=False, index=True)
    screen_on_at = Column(DateTime, nullable=False)
    screen_off_at = Column(DateTime, nullable=False)
    duration_seconds = Column(Float, nullable=False) # Total seconds the screen was ON
    created_at = Column(DateTime, default=datetime.utcnow)

    device = relationship("Device", back_populates="logs")
