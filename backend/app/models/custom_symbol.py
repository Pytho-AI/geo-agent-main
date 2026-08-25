from sqlalchemy import Column, String, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid

from app.models.base import Base


class CustomSymbol(Base):
    __tablename__ = "custom_symbols"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    file_format = Column(String(10), nullable=False)  # "png" | "svg"
    mime_type = Column(String(100), nullable=False)
    storage_uri = Column(String(1024), nullable=False)
    width = Column(Integer)
    height = Column(Integer)
    created_by = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
