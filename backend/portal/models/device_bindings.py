from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class DeviceBindings(db.Model, TimestampMixin, CRUDMixin):
    """
    PRD FR-001: device UUID and carrier signature are stored to prevent remote
    session hijacking; a mismatch triggers step-up authentication.
    """

    __tablename__ = 'device_bindings'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'device_uuid', name='uq_user_device'),
    )

    device_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, index=True)

    device_uuid = db.Column(db.String(100), nullable=False, index=True)
    device_name = db.Column(db.String(150), nullable=True)
    platform = db.Column(db.String(50), nullable=True)
    carrier_signature = db.Column(db.String(255), nullable=True)

    is_trusted = db.Column(db.Boolean, default=False)
    last_seen_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('Users', back_populates='devices')

    def __repr__(self):
        return f"<Device {self.device_uuid} trusted={self.is_trusted}>"
