# rag/utils/auth_utils.py
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Any, Mapping

from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError
from passlib.context import CryptContext


@dataclass(frozen=True)
class JwtSigningConfig:
    secret_key: str
    algorithm: str = "HS256"


class AuthUtils:
    pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

    # Legacy routes retain their historical fallback. Advanced startup must use
    # configure_advanced_signing(), which rejects missing/default authority.
    _LEGACY_DEFAULT_SECRET = "br-chat-aision"
    SECRET_KEY = os.getenv("JWT_SECRET_KEY", _LEGACY_DEFAULT_SECRET)
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7

    @classmethod
    def verify_password(cls, stored_password, plain_password):
        if (
            stored_password.startswith("$2b$")
            or stored_password.startswith("$2a$")
            or stored_password.startswith("$pbkdf2-sha256$")
        ):
            return cls.pwd_context.verify(plain_password, stored_password)
        return stored_password == plain_password

    @classmethod
    def hash_password(cls, password):
        password_bytes = (
            password.encode("utf-8") if isinstance(password, str) else password
        )
        if len(password_bytes) > 72:
            password_bytes = password_bytes[:72]
            password = (
                password_bytes.decode("utf-8", errors="ignore")
                if isinstance(password, str)
                else password_bytes
            )
        return cls.pwd_context.hash(password)

    @classmethod
    def advanced_signing_config(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> JwtSigningConfig:
        """Return explicit advanced signing config or fail startup closed."""
        values = os.environ if environ is None else environ
        configured = values.get("JWT_SECRET_KEY")
        if not configured or configured == cls._LEGACY_DEFAULT_SECRET:
            raise RuntimeError(
                "advanced JWT signing authority is not explicitly configured"
            )
        return JwtSigningConfig(
            secret_key=configured,
            algorithm=cls.ALGORITHM,
        )

    @classmethod
    def configure_advanced_signing(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> JwtSigningConfig:
        """Validate and activate one shared issuer/verifier configuration."""
        config = cls.advanced_signing_config(environ)
        cls.SECRET_KEY = config.secret_key
        cls.ALGORITHM = config.algorithm
        return config

    @classmethod
    def create_access_token(
        cls,
        data: Dict,
        signing_config: JwtSigningConfig | None = None,
    ):
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(
            minutes=cls.ACCESS_TOKEN_EXPIRE_MINUTES
        )
        to_encode.update({"exp": expire})
        config = signing_config or JwtSigningConfig(
            secret_key=cls.SECRET_KEY,
            algorithm=cls.ALGORITHM,
        )
        return jwt.encode(
            to_encode,
            config.secret_key,
            algorithm=config.algorithm,
        )

    @classmethod
    def decode_token(
        cls,
        token: str,
        signing_config: JwtSigningConfig | None = None,
    ):
        config = signing_config or JwtSigningConfig(
            secret_key=cls.SECRET_KEY,
            algorithm=cls.ALGORITHM,
        )
        try:
            return jwt.decode(
                token,
                config.secret_key,
                algorithms=[config.algorithm],
            )
        except JWTError:
            return None

    @staticmethod
    def verify_access_token(
        token: str,
        signing_config: JwtSigningConfig | None = None,
    ) -> dict[str, Any]:
        config = signing_config or JwtSigningConfig(
            secret_key=AuthUtils.SECRET_KEY,
            algorithm=AuthUtils.ALGORITHM,
        )
        try:
            return jwt.decode(
                token,
                config.secret_key,
                algorithms=[config.algorithm],
            )
        except ExpiredSignatureError as exc:
            raise ValueError("token expired") from exc
        except JWTError as exc:
            raise ValueError("invalid token") from exc


__all__ = ["AuthUtils", "JwtSigningConfig"]
