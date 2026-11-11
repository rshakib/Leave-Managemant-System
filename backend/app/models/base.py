from sqlalchemy import BigInteger, Column, DateTime, func
from sqlalchemy.orm import declared_attr


class BaseModel:
    @declared_attr
    def created_at(cls):  # noqa: N805
        return Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        )

    @declared_attr
    def updated_at(cls):  # noqa: N805
        return Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        )

    @declared_attr
    def created_by(cls):  # noqa: N805
        return Column(BigInteger, nullable=True)
