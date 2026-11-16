"""The public setup tool must never ship shared login credentials."""
import hashlib
import runpy
from pathlib import Path

import pytest

generate = runpy.run_path(str(Path(__file__).parents[1] / 'scripts/create-web-auth.py'))['generate']

def test_generated_login_matches_server_derivation_and_is_unique():
    password = 'test-only-password-12345'
    first, second = generate('test-owner', password), generate('test-owner', password)
    expected = hashlib.pbkdf2_hmac('sha256', password.encode(), first['AUTH_PASSWORD_SALT'].encode(), 100000, 32).hex()
    assert first['AUTH_PASSWORD_HASH'] == expected
    assert first['AUTH_PASSWORD_SALT'] != second['AUTH_PASSWORD_SALT']
    assert first['AUTH_SESSION_SECRET'] != second['AUTH_SESSION_SECRET']
    assert len(first['AUTH_SESSION_SECRET']) == 64
    assert password not in first.values()

def test_setup_requires_an_owner_and_nondefault_password():
    with pytest.raises(ValueError):
        generate('', 'test-only-password-12345')
    with pytest.raises(ValueError):
        generate('test-owner', 'short')
