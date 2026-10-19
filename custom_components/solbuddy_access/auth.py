"""Fail-closed authentication boundary. Phase 2 issues no guest credentials."""


class GuestAccessDisabled(PermissionError):
    """Guest authentication is not implemented or exposed."""


class GuestAuthenticator:
    """Reject every credential; never substitute an HA owner principal."""

    async def authenticate(self, credential: object = None) -> None:
        raise GuestAccessDisabled("Guest access is disabled")
