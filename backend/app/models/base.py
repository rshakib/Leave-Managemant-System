from sqlalchemy import BigInteger, Column, DateTime, func
from sqlalchemy.orm import declared_attr


class BaseModel:
    """Shared audit columns for every table model.

    A plain SQLAlchemy mixin (not a table). Inherit it *before* ``SQLModel``::

        class Division(BaseModel, SQLModel, table=True): ...

    It uses ``declared_attr`` so each table gets its own ``Column`` objects — a
    plain mixin sharing one ``Column`` instance across tables makes SQLAlchemy
    raise "Column object already assigned to Table".

    Columns:
    - ``created_at`` / ``updated_at`` — timezone-aware UTC ``timestamptz``,
      defaulted by the database (DECISIONS D-21). ``updated_at`` refreshes on
      every UPDATE.
    - ``created_by`` — nullable employee id; plain ``BIGINT`` for now, so it
      lines up with ``audit_log.entity_id`` (DECISIONS D-24). Becomes a foreign
      key to ``employee.id`` in Phase 3.
    """

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
