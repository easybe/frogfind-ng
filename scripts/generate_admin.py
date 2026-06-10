"""
Run once to generate ADMIN_PATH, ADMIN_SECRET_KEY, and ADMIN_PASSWORD_HASH.

Usage:
    python scripts/generate_admin.py
"""

import getpass
import secrets
import sys

sys.path.insert(0, ".")

try:
    import bcrypt
except ImportError:
    print("bcrypt not installed. Run: pip install bcrypt")
    sys.exit(1)

print("=" * 60)
print("  FrogFind NG — Admin Setup")
print("=" * 60)
print()

password = getpass.getpass("Choose admin password: ")
if len(password) < 8:
    print("Password must be at least 8 characters.")
    sys.exit(1)

confirm = getpass.getpass("Confirm password: ")
if password != confirm:
    print("Passwords do not match.")
    sys.exit(1)

admin_path    = "admin-" + secrets.token_hex(8)
secret_key    = secrets.token_hex(32)
password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

print()
print("Add the following to your .env file:")
print()
print(f"ADMIN_PATH={admin_path}")
print(f"ADMIN_SECRET_KEY={secret_key}")
print(f"ADMIN_PASSWORD_HASH={password_hash}")
print()
print(f"Admin panel: http://your-host/{admin_path}/login")
print()
print("Never commit .env to version control.")
