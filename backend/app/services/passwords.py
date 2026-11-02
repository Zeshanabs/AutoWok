from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

password_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def validate_password_strength(password: str) -> None:
    if (
        len(password) < 12
        or not any(character.islower() for character in password)
        or not any(character.isupper() for character in password)
        or not any(character.isdigit() for character in password)
        or not any(not character.isalnum() for character in password)
    ):
        raise ValueError(
            "Password must be at least 12 characters and include uppercase, lowercase, "
            "a number, and a symbol."
        )


def hash_password(password: str) -> str:
    validate_password_strength(password)
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
