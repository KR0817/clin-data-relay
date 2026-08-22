"""Small credential helpers shared by the local repository and HTTP layer."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error


DEMO_PASSWORD = "demo-password"
SETUP_REQUIRED_PASSWORD_HASH = "!setup-required"
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_PASSWORD_GROUPS = (
    "ABCDEFGHJKLMNPQRSTUVWXYZ",
    "abcdefghijkmnopqrstuvwxyz",
    "23456789",
    "!@#$%*-_=+",
)


def password_digest(password: str) -> str:
    """Return the legacy synthetic-account digest used by the sandbox only."""

    return hashlib.sha256(f"clinical-edc-companion:{password}".encode("utf-8")).hexdigest()


def strong_password(password: str) -> bool:
    return (
        16 <= len(password) <= 128
        and any(character.islower() for character in password)
        and any(character.isupper() for character in password)
        and any(character.isdigit() for character in password)
        and any(not character.isalnum() for character in password)
    )


def generate_strong_password(length: int = 24) -> str:
    if length < 16:
        raise ValueError("password_length_too_short")
    characters = [secrets.choice(group) for group in _PASSWORD_GROUPS]
    characters.extend(secrets.choice("".join(_PASSWORD_GROUPS)) for _ in range(length - len(characters)))
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


def password_hash(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=32,
    )
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N,
        _SCRYPT_R,
        _SCRYPT_P,
        urlsafe_b64encode(salt).decode("ascii"),
        urlsafe_b64encode(derived).decode("ascii"),
    )


def verify_password(password: str, encoded: str, *, allow_legacy_demo: bool = False) -> bool:
    if encoded == SETUP_REQUIRED_PASSWORD_HASH:
        return False
    if not encoded.startswith("scrypt$"):
        return allow_legacy_demo and hmac.compare_digest(password_digest(password), encoded)
    try:
        _, n, r, p, salt, expected = encoded.split("$", 5)
        parameters = (int(n), int(r), int(p))
        if parameters != (_SCRYPT_N, _SCRYPT_R, _SCRYPT_P):
            return False
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=urlsafe_b64decode(salt.encode("ascii")),
            n=parameters[0],
            r=parameters[1],
            p=parameters[2],
            dklen=32,
        )
        return hmac.compare_digest(derived, urlsafe_b64decode(expected.encode("ascii")))
    except (Base64Error, ValueError, TypeError):
        return False
