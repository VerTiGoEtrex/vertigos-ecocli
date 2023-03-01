import requests
import click
import json
import logging
from pathlib import Path
from oauthlib.oauth2 import Client as OAuthClientUNIQ
from oauthlib.oauth2 import MobileApplicationClient, WebApplicationClient
from oauthlib.oauth2.rfc6749.parameters import prepare_grant_uri, prepare_token_request
from requests_oauthlib import OAuth2Session

# logging.basicConfig(level=logging.DEBUG)

config_path = Path("~/.config/vertigos-ecocli/conf.json").expanduser()
config = json.load(config_path.open('r'))

selection = {
            'selectionType': 'thermostats',
            'selectionMatch': '511876645706', # upstairs thermostat
            'includeSettings': True,
            'includeRuntime': True,
        }

class EcobeeOAuthClient(OAuthClientUNIQ):

    grant_type = 'ecobeePin'

    # response_type = 'ecobeePin'
    def prepare_request_uri(self, uri, **kwargs):
        return prepare_grant_uri(uri, self.client_id, 'ecobeePin', **kwargs)
    
    def prepare_request_body(self, code=None, body='',
                            include_client_id=True, code_verifier=None, **kwargs):
        """Prepare the access token request body.

        The client makes a request to the token endpoint by adding the
        following parameters using the "application/x-www-form-urlencoded"
        format in the HTTP request entity-body:

        :param code:    REQUIRED. The authorization code received from the
                        authorization server.

        :param redirect_uri:    REQUIRED, if the "redirect_uri" parameter was included in the
                                authorization request as described in `Section 4.1.1`_, and their
                                values MUST be identical.

        :param body: Existing request body (URL encoded string) to embed parameters
                     into. This may contain extra parameters. Default ''.

        :param include_client_id: `True` (default) to send the `client_id` in the
                                  body of the upstream request. This is required
                                  if the client is not authenticating with the
                                  authorization server as described in `Section 3.2.1`_.
        :type include_client_id: Boolean

        :param code_verifier: OPTIONAL. A cryptographically random string that is used to correlate the
                                        authorization request to the token request.

        :param kwargs: Extra parameters to include in the token request.

        In addition OAuthLib will add the ``grant_type`` parameter set to
        ``authorization_code``.

        If the client type is confidential or the client was issued client
        credentials (or assigned other authentication requirements), the
        client MUST authenticate with the authorization server as described
        in `Section 3.2.1`_::

            >>> from oauthlib.oauth2 import WebApplicationClient
            >>> client = WebApplicationClient('your_id')
            >>> client.prepare_request_body(code='sh35ksdf09sf')
            'grant_type=authorization_code&code=sh35ksdf09sf'
            >>> client.prepare_request_body(code_verifier='KB46DCKJ873NCGXK5GD682NHDKK34GR')
            'grant_type=authorization_code&code_verifier=KB46DCKJ873NCGXK5GD682NHDKK34GR'
            >>> client.prepare_request_body(code='sh35ksdf09sf', foo='bar')
            'grant_type=authorization_code&code=sh35ksdf09sf&foo=bar'

        `Section 3.2.1` also states:
            In the "authorization_code" "grant_type" request to the token
            endpoint, an unauthenticated client MUST send its "client_id" to
            prevent itself from inadvertently accepting a code intended for a
            client with a different "client_id".  This protects the client from
            substitution of the authentication code.  (It provides no additional
            security for the protected resource.)

        .. _`Section 4.1.1`: https://tools.ietf.org/html/rfc6749#section-4.1.1
        .. _`Section 3.2.1`: https://tools.ietf.org/html/rfc6749#section-3.2.1
        """
        code = code or self.code
        
        kwargs['client_id'] = self.client_id
        kwargs['include_client_id'] = include_client_id
        return prepare_token_request(self.grant_type, code=code, body=body, code_verifier=code_verifier, **kwargs)

    def prepare_refresh_body(self, body='', refresh_token=None, scope=None, **kwargs):
        """Prepare an access token request, using a refresh token.

        If the authorization server issued a refresh token to the client, the
        client makes a refresh request to the token endpoint by adding the
        following parameters using the `application/x-www-form-urlencoded`
        format in the HTTP request entity-body:

        :param refresh_token: REQUIRED.  The refresh token issued to the client.
        :param scope:  OPTIONAL.  The scope of the access request as described by
            Section 3.3.  The requested scope MUST NOT include any scope
            not originally granted by the resource owner, and if omitted is
            treated as equal to the scope originally granted by the
            resource owner. Note that if none is provided, the ones provided
            in the constructor are used if any.
        """
        refresh_token = refresh_token or self.refresh_token
        scope = self.scope if scope is None else scope
        return prepare_token_request(self.refresh_token_key, body=body, scope=scope,
                                     code=refresh_token, include_client_id=True, client_id=self.client_id, **kwargs)

@click.group()
@click.pass_context
def cli(ctx):
    def token_saver(token):
        config['saved_token'] = token
        json.dump(config, config_path.open('w'))

    scopes = ['openid,smartWrite,offline_access']
    client = EcobeeOAuthClient(client_id=config['client_id'])
    client.response_type = 'ecobeePin'
    oauth = OAuth2Session(
        client=client,
        scope=scopes,
        token=config.get('saved_token', None),
        auto_refresh_url='https://api.ecobee.com/token',
        token_updater=token_saver,
    )

    if config.get('saved_token', None) == None:
        click.echo("Need a token!")
        # Initial "login"
        authorization_url, state = oauth.authorization_url("https://api.ecobee.com/authorize", scopes)
        response = oauth.get(authorization_url)
        response.raise_for_status()
        click.echo(f"Please go to https://www.ecobee.com/consumerportal/index.html#/my-apps/add/new and provide this code: {response.json()['ecobeePin']}")
        input("Press enter once authorization has been granted!")

        # Get initial token
        # initial_token = oauth.post(f"https://api.ecobee.com/token?grant_type=ecobeePin&code={response.json()['code']}&client_id={config['client_id']}")
        # initial_token.raise_for_status()
        # click.echo(f"Initial token: {initial_token.json()}")
        oauth.fetch_token("https://api.ecobee.com/token", code=response.json()['code'], include_client_id=True, )
        click.echo(f'got token! {oauth.token}')
        token_saver(oauth.token)
    
    ctx.ensure_object(dict)
    ctx.obj['oauth'] = oauth

@cli.command()
@click.pass_context
def get_status(ctx):
    ctx.ensure_object(dict)
    oauth = ctx.obj['oauth']
    body = {
        'selection': selection,
    }

    res = oauth.get(f'https://api.ecobee.com/1/thermostat', params={'format': 'json', 'body': json.dumps(body)})
    # click.echo(res.json())
    res.raise_for_status()
    ts = res.json()['thermostatList'][0]

    current_mode = ts['settings']['hvacMode']
    heat_range_high = ts['settings']['heatRangeHigh']
    heat_range_low = ts['settings']['heatRangeLow']
    cool_range_high = ts['settings']['coolRangeHigh']
    cool_range_low = ts['settings']['coolRangeLow']

    click.echo(f'current mode: {current_mode}')
    click.echo(f'current temp: {ts["runtime"]["actualTemperature"]/10}')
    click.echo(f'desired heat: {ts["runtime"]["desiredHeat"]/10}')
    click.echo(f'desired cool: {ts["runtime"]["desiredCool"]/10}')
    click.echo(f'heat range: {heat_range_low / 10} - {heat_range_high / 10}')
    click.echo(f'cool range: {cool_range_low / 10} - {cool_range_high / 10}')
    

@cli.command()
@click.argument('mode', required=True, type=click.Choice(['heat', 'cool', 'off'], case_sensitive=False))
@click.pass_context
def set_mode(ctx, mode: str):
    ctx.ensure_object(dict)
    oauth = ctx.obj['oauth']

    body = {
        'selection': selection,
        'thermostat': {
            'settings': {
                'hvacMode': mode
            }
        }
    }
    res = oauth.post(f'https://api.ecobee.com/1/thermostat', params={'format': 'json', 'body': json.dumps(body)})
    click.echo(res.json())
    res.raise_for_status()

@cli.command()
@click.argument('temp', required=True, type=float)
@click.argument('duration-hours', required=False, type=int)
@click.pass_context
def set_temp(ctx, temp: float, duration_hours: int):
    ctx.ensure_object(dict)
    oauth = ctx.obj['oauth']

    hold_params = {
        "holdType":"nextTransition" if duration_hours == None else 'holdHours',
        "heatHoldTemp":int(temp*10),
        "coolHoldTemp":int(temp*10),
    }
    if duration_hours != None:
        hold_params['holdHours'] = duration_hours

    body = {
        'selection': selection,
        "functions": [
            {
                "type":"setHold",
                "params": hold_params
            }
        ]
    }
    res = oauth.post(f'https://api.ecobee.com/1/thermostat', params={'format': 'json', 'body': json.dumps(body)})
    click.echo(res.json())
    res.raise_for_status()

@cli.command()
@click.pass_context
def resume_program(ctx):
    ctx.ensure_object(dict)
    oauth = ctx.obj['oauth']

    body = {
        'selection': selection,
        "functions": [
            {
                "type":"resumeProgram",
                "params":{
                    "resumeAll": False
                }      
            }
        ]
    }
    res = oauth.post(f'https://api.ecobee.com/1/thermostat', params={'format': 'json', 'body': json.dumps(body)})
    click.echo(res.json())
    res.raise_for_status()

if __name__ == '__main__':
    cli(obj={})