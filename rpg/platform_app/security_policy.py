"""Validated security settings shared by authentication and the admin API."""
from ipaddress import ip_address, ip_network

from pydantic import BaseModel, Field, field_validator

from .db import connect

KEY = "admin.security_config"


class SecurityPolicy(BaseModel):
    ip_blocklist: list[str] = Field(default_factory=list, max_length=1000)
    rate_limit_per_ip: int = Field(default=30, ge=1, le=10000)
    rate_limit_per_user: int = Field(default=5, ge=1, le=1000)
    rate_window_minutes: int = Field(default=10, ge=1, le=1440)
    password_min_length: int = Field(default=8, ge=8, le=128)
    password_require_numbers: bool = False
    session_timeout_days: int = Field(default=14, ge=1, le=90)
    login_lock_threshold: int = Field(default=5, ge=1, le=1000)
    login_lock_duration_min: int = Field(default=1, ge=1, le=1440)

    @field_validator("ip_blocklist")
    @classmethod
    def valid_networks(cls, values):
        return [str(ip_network(value.strip(), strict=False)) for value in values]


def read(db=None):
    if db is None:
        with connect() as conn:
            return read(conn)
    row = db.execute("select value from app_config where key=%s", (KEY,)).fetchone()
    stored = (row or {}).get("value")
    # Ignore obsolete/unknown fields from older versions, retaining safe defaults.
    stored = stored if isinstance(stored, dict) else {}
    from core.config import min_password_length
    defaults = SecurityPolicy(password_min_length=max(8, min(128, min_password_length()))).model_dump()
    for key, value in stored.items():
        if key in defaults:
            try:
                defaults[key] = SecurityPolicy(**{key: value}).model_dump()[key]
            except ValueError:
                pass
    return defaults


def validate_password(password, db=None):
    cfg = read(db)
    if len(password or "") < cfg["password_min_length"]:
        raise ValueError(f"密码至少 {cfg['password_min_length']} 位")
    if len(password or "") > 1024:
        raise ValueError("密码超长")
    if cfg["password_require_numbers"] and not any(ch.isdecimal() for ch in password):
        raise ValueError("密码需要包含数字")


def blocked(ip, cfg):
    try:
        address = ip_address(ip)
    except ValueError:
        return False
    return any(address in ip_network(network) for network in cfg["ip_blocklist"])
