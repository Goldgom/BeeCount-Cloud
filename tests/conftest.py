import os

# Keep guardrail tests deterministic regardless of local .env defaults.
os.environ.setdefault("ALLOW_APP_RW_SCOPES", "false")
# Self-hosted registration defaults to off; test suite needs it on so the
# fixture helpers that create users via POST /auth/register keep working.
os.environ.setdefault("REGISTRATION_ENABLED", "true")
# Finance scheduler is tested explicitly with an in-memory session factory.
os.environ["FINANCE_SNAPSHOT_SCHEDULER_ENABLED"] = "false"
