import time

import jwt as pyjwt

from auth.jwt_utils import create_access_token, decode_access_token


def test_valid_token_roundtrips():
    token = create_access_token("alice", "operator")
    payload = decode_access_token(token)
    assert payload["sub"] == "alice"
    assert payload["role"] == "operator"


def test_expired_token_rejected():
    token = create_access_token("bob", "viewer", expires_minutes=0)
    time.sleep(1.2)
    try:
        decode_access_token(token)
        assert False, "expected ExpiredSignatureError"
    except pyjwt.ExpiredSignatureError:
        pass


def test_tampered_token_rejected():
    token = create_access_token("alice", "admin")
    tampered = token[:-3] + "xyz"
    try:
        decode_access_token(tampered)
        assert False, "expected InvalidTokenError"
    except pyjwt.InvalidTokenError:
        pass
