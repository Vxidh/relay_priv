import urllib.parse
import logging
from django.contrib.auth.models import AnonymousUser
from oauth2_provider.models import AccessToken
from django.utils import timezone
from channels.db import database_sync_to_async

logger = logging.getLogger(__name__)

class TokenAuthMiddleware:
    """
    ASGI 3 middleware for Channels that authenticates WebSocket connections using OAuth2 tokens.
    """
    def __init__(self, app):

        
        self.app = app

    async def __call__(self, scope, receive, send):
        query_string = scope.get('query_string', b'').decode()
        query_params = urllib.parse.parse_qs(query_string)
        token = query_params.get('token', [None])[0]
        logger.info(f"TokenAuthMiddleware: Received token: {token}")
        user = await self.get_user(token)
        logger.info(f"TokenAuthMiddleware: User authenticated: {user.is_authenticated if hasattr(user, 'is_authenticated') else 'N/A'} (user={user})")
        scope['user'] = user
        return await self.app(scope, receive, send)

    @database_sync_to_async
    def get_user(self, token):
        if not token:
            logger.warning("TokenAuthMiddleware: No token provided in query string.")
            return AnonymousUser()
        try:
            access_token = AccessToken.objects.select_related('user').get(token=token, expires__gt=timezone.now())
            logger.info(f"TokenAuthMiddleware: Access token found for user {access_token.user}")
            return access_token.user if access_token.user.is_active else AnonymousUser()
        except AccessToken.DoesNotExist:
            logger.warning("TokenAuthMiddleware: Invalid or expired token.")
            return AnonymousUser()
