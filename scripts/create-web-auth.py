#!/usr/bin/env python3
"""Create private login settings locally. No network calls or shared password."""
import argparse
import getpass
import hashlib
import json
import os
import secrets
from pathlib import Path

def generate(username, password):
    if not username.strip() or len(password) < 12:
        raise ValueError('Use a nonempty username and a password of at least 12 characters.')
    salt = secrets.token_hex(16)
    return {'AUTH_USERNAME': username, 'AUTH_PASSWORD_SALT': salt,
            'AUTH_PASSWORD_HASH': hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000, 32).hex(),
            'AUTH_SESSION_SECRET': secrets.token_hex(32)}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('.local/web-auth.json'))
    args = parser.parse_args()
    username = input('New workbench username: ').strip()
    password = getpass.getpass('New password (12+ characters): ')
    if password != getpass.getpass('Repeat password: '):
        raise SystemExit('Passwords do not match.')
    value = generate(username, password)
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f)
    print(f'Created {args.output}; set its JSON content as the private WORKBENCH_AUTH runtime secret.')
    print('This file contains a password hash and session-signing secret. Do not commit it.')
