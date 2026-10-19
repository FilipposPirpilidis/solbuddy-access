"""Integration constants; no credential material belongs here."""

DOMAIN = "solbuddy_access"
STORAGE_VERSION = 1
MAX_GRANTS = 100
MAX_ENTITIES = 32
MAX_DURATION_DAYS = 30

# Phase 3 security tests passed; runtime guest access still requires owner opt-in.
GUEST_TRANSPORT_VERIFIED = True
