from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://karyuk:karyuk@localhost:5432/karyuk"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    dev_auth_enabled: bool = True
    jwt_secret: str = "dev-secret-change-me"
    jwt_issuer: str = "karyuk-dev"
    jwt_audience: str = "karyuk-api"
    access_token_expire_minutes: int = 60 * 24

    keycloak_enabled: bool = False
    keycloak_issuer: str = "http://localhost:8080/realms/karyuk"
    keycloak_audience: str = "karyuk-api"
    keycloak_jwks_url: str = (
        "http://localhost:8080/realms/karyuk/protocol/openid-connect/certs"
    )

    # Public URL for telephony webhooks (ngrok / production host)
    public_api_base_url: str = "http://127.0.0.1:8000"
    telephony_provider: str = "auto"  # auto | simulate | exotel

    exotel_subdomain: str = ""
    exotel_api_base_url: str = ""  # e.g. https://api.exotel.com (Singapore)
    exotel_account_sid: str = ""
    exotel_api_key: str = ""
    exotel_api_token: str = ""
    exotel_caller_id: str = ""
    exotel_whatsapp_enabled: bool = False
    exotel_whatsapp_from: str = ""  # ExoPhone or virtual number (E.164)

    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_sip_uri: str = ""  # optional: sip trunk for Exotel <Dial><Sip>
    livekit_agent_name: str = "karyuk-voice"
    # When false: keep caller on Exotel audio (no SIP dial) — use if LiveKit SIP is not provisioned yet
    inbound_dial_livekit: bool = True
    # auto | livekit | exotel_gemini | sarvam — sarvam = Saaras STT + 105B chat + Bulbul TTS (Voicebot)
    inbound_voice_mode: str = "auto"
    # m05 = legacy karyuk-m05 handbook (Anitha demo). employee = Your Team published brief (default).
    voice_agent_profile: str = "employee"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    sarvam_api_key: str = ""
    # none = callback promise only; exotel_transfer = may speak live transfer (when wired)
    voice_transfer_mode: str = "none"
    manager_callback_minutes: int = 15
    owner_notify_email: str = ""
    owner_notify_phone: str = ""
    owner_notify_whatsapp: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    voice_barge_in: str = "off"  # env: VOICE_BARGE_IN=on|off

    # Inbound Exotel (ExoPhone → voice URL) routing when DB has no phone_numbers row
    exotel_inbound_fallback_workspace_id: str = ""
    exotel_inbound_fallback_employee_id: str = ""

    # Outpero (lead intake + post-call webhooks). Per-agent secrets live in DB.
    outpero_api_base_url: str = "https://api.outpero.com"
    outpero_webhook_max_age_seconds: int = 300
    outpero_webhook_shared_secret: str = ""  # optional workspace-wide fallback HMAC secret
    # Bootstrap a workspace agent from env (Instant leads / Team will dial via this).
    outpero_default_name: str = "Primary voice agent"
    outpero_default_slug: str = ""
    outpero_default_lead_secret: str = ""
    outpero_default_webhook_secret: str = ""
    outpero_default_workspace_id: str = ""  # defaults to first workspace if empty
    # When true and an active agent exists, Instant/Team outbound uses Outpero (skips Exotel KYC).
    outpero_prefer_outbound: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()