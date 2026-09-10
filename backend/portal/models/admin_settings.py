from portal import db
from portal.models.base import TimestampMixin, CRUDMixin


class SettingDataType:
    STRING = "STRING"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    BOOLEAN = "BOOLEAN"
    JSON = "JSON"

    CHOICES = [STRING, INTEGER, DECIMAL, BOOLEAN, JSON]


class AdminSettings(db.Model, TimestampMixin, CRUDMixin):
    """
    Runtime platform configuration (PRD 16.1 settings module).

    Transaction limits and the convenience fee live here rather than in code
    because they are commercial levers that change without a deploy - and
    because every change is then captured in admin_activity_logs.
    """

    __tablename__ = 'admin_settings'

    setting_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    setting_key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    setting_value = db.Column(db.String(1000), nullable=False)
    default_value = db.Column(db.String(1000), nullable=True)
    data_type = db.Column(db.String(20), default=SettingDataType.STRING)

    category = db.Column(db.String(50), nullable=True, index=True)
    display_name = db.Column(db.String(200), nullable=True)
    description = db.Column(db.String(500), nullable=True)

    # Guard rails so an operator cannot set a fee of 900% by fat-finger.
    min_value = db.Column(db.String(50), nullable=True)
    max_value = db.Column(db.String(50), nullable=True)

    is_editable = db.Column(db.Boolean, default=True)
    requires_restart = db.Column(db.Boolean, default=False)

    updated_by = db.Column(db.String(36), nullable=True)

    def __repr__(self):
        return f"<Setting {self.setting_key}={self.setting_value}>"


class FlagRolloutType:
    BOOLEAN = "BOOLEAN"
    PERCENTAGE = "PERCENTAGE"
    USER_LIST = "USER_LIST"

    CHOICES = [BOOLEAN, PERCENTAGE, USER_LIST]


class FeatureFlags(db.Model, TimestampMixin, CRUDMixin):
    """
    Feature toggles. The credit-to-bank transfer flag matters most: PRD open
    decision 1 leaves its legal model unresolved, so the whole feature must be
    switchable off without a deploy.
    """

    __tablename__ = 'feature_flags'

    flag_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    flag_key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(200), nullable=True)
    description = db.Column(db.String(500), nullable=True)

    is_enabled = db.Column(db.Boolean, default=False)
    rollout_type = db.Column(db.String(20), default=FlagRolloutType.BOOLEAN)
    rollout_percentage = db.Column(db.Integer, default=0)
    target_user_ids = db.Column(db.Text, nullable=True)     # JSON array

    updated_by = db.Column(db.String(36), nullable=True)

    def __repr__(self):
        return f"<Flag {self.flag_key}={self.is_enabled}>"
