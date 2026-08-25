import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Audit(Base):
    __tablename__ = "audits"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    response_text: Mapped[str] = mapped_column(String)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    source_system: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    grounded_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    claim_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    claims: Mapped[list["AuditClaim"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan"
    )
    source_chunks: Mapped[list["AuditSourceChunk"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan"
    )


class AuditClaim(Base):
    __tablename__ = "audit_claims"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_id: Mapped[str] = mapped_column(ForeignKey("audits.id"))
    claim_text: Mapped[str] = mapped_column(String)
    verdict: Mapped[str] = mapped_column(String)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    rationale: Mapped[str] = mapped_column(String, default="")

    audit: Mapped["Audit"] = relationship(back_populates="claims")


class AuditSourceChunk(Base):
    __tablename__ = "audit_source_chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_id: Mapped[str] = mapped_column(ForeignKey("audits.id"))
    chunk_id: Mapped[str] = mapped_column(String)
    chunk_text: Mapped[str] = mapped_column(String)

    audit: Mapped["Audit"] = relationship(back_populates="source_chunks")
