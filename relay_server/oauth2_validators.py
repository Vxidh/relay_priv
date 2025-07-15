# File: relay_server/oauth2_validators.py

from oauth2_provider.oauth2_validators import OAuth2Validator
from oauth2_provider.models import AccessToken

class CustomOAuth2Validator(OAuth2Validator):
    """
    Custom OAuth2Validator to ensure that AccessTokens generated via
    Client Credentials Grant are associated with the User linked to the Application.
    """

    def save_token(self, token, request, *args, **kwargs):
        """
        Overrides the default save_token to explicitly set the user for client credentials grant.
        """
        # Call the original save_token method first to create the AccessToken
        super().save_token(token, request, *args, **kwargs)

        # For Client Credentials Grant, the request.client is the Application object.
        # The user associated with this Application is the one we want to link the token to.
        if request.grant_type == 'client_credentials' and request.client:
            # Retrieve the AccessToken instance that was just created
            try:
                access_token_obj = AccessToken.objects.get(token=token['access_token'])
                # If the application has a user associated, link it to the token
                if request.client.user:
                    access_token_obj.user = request.client.user
                    access_token_obj.save()
                    # Log for debugging
                    print(f"DEBUG: Linked AccessToken {access_token_obj.token} to user {access_token_obj.user.username} for Client Credentials Grant.")
                else:
                    print(f"DEBUG: Client Credentials Grant for app {request.client.name} has no associated user. Token {access_token_obj.token} remains unlinked.")
            except AccessToken.DoesNotExist:
                print(f"ERROR: AccessToken {token['access_token']} not found after creation in save_token.")
            except Exception as e:
                print(f"ERROR: Failed to link user to AccessToken for Client Credentials Grant: {e}")
