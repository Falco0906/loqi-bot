from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass
class Argon2Config:
    memory_cost: int = 65536
    time_cost: int = 3
    parallelism: int = 4
    hash_len: int = 32
    salt_len: int = 16


@dataclass
class TokenConfig:
    verification_token_bytes: int = 32
    refresh_token_bytes: int = 32
    password_reset_token_bytes: int = 32
    session_token_bytes: int = 32
    invitation_token_bytes: int = 32

    verification_token_ttl_seconds: int = 900
    password_reset_ttl_seconds: int = 900
    invitation_ttl_seconds: int = 604800

    refresh_token_ttl_seconds: int = 2592000
    session_ttl_seconds: int = 900


@dataclass
class SessionConfig:
    max_active_sessions_per_user: int = 25
    extend_on_activity: bool = True
    session_token_ttl_seconds: int = 900


@dataclass
class PasswordConfig:
    min_length: int = 12
    require_uppercase: bool = True
    require_lowercase: bool = True
    require_digit: bool = True
    require_special: bool = True


@dataclass
class GoogleOAuthConfig:
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    scopes: str = "openid email profile"
    auth_uri: str = "https://accounts.google.com/o/oauth2/v2/auth"
    token_uri: str = "https://oauth2.googleapis.com/token"
    jwks_uri: str = "https://www.googleapis.com/oauth2/v3/certs"
    issuer: str = "https://accounts.google.com"
    clock_skew_seconds: int = 30
    oauth_session_ttl_seconds: int = 600


@dataclass
class IdentityConfig:
    argon2: Argon2Config = field(default_factory=Argon2Config)
    tokens: TokenConfig = field(default_factory=TokenConfig)
    sessions: SessionConfig = field(default_factory=SessionConfig)
    password: PasswordConfig = field(default_factory=PasswordConfig)
    google_oauth: GoogleOAuthConfig = field(default_factory=GoogleOAuthConfig)
    crypto_hash_algorithm: str = "sha256"
    crypto_encryption_algorithm: str = "aes-256-gcm"
    signing_key_id: str = "default"
    max_login_attempts: int = 5
    login_lockout_seconds: int = 300


IDENTITY_CONFIG = IdentityConfig()

load_dotenv()
IDENTITY_CONFIG.google_oauth.client_id = os.getenv("GOOGLE_CLIENT_ID", "")
IDENTITY_CONFIG.google_oauth.client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
IDENTITY_CONFIG.google_oauth.redirect_uri = f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/auth/google/callback"
