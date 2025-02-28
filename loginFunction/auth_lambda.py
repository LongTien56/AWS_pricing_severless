import json
import boto3
import requests
import os
from authlib.integrations.requests_client import OAuth2Session
from botocore.exceptions import ClientError


# Load Cognito details from AWS SSM Parameter Store
ssm = boto3.client("ssm")
USER_POOL_ID = ssm.get_parameter(Name="/auth/user-pool-id", WithDecryption=True)["Parameter"]["Value"]
CLIENT_ID = ssm.get_parameter(Name="/auth/app-client-id", WithDecryption=True)["Parameter"]["Value"]

#Secret Manager
secret_name = "auth/bom/client_secret"
region_name = "us-east-1"

# Cognito OIDC URLs
COGNITO_DOMAIN = ssm.get_parameter(Name="/auth/cognito-domain", WithDecryption=True)["Parameter"]["Value"]
AUTHORIZATION_URL = f"{COGNITO_DOMAIN}/oauth2/authorize"
TOKEN_URL = f"{COGNITO_DOMAIN}/oauth2/token"
USERINFO_URL = f"{COGNITO_DOMAIN}/oauth2/userInfo"
LOGOUT_URL = f"{COGNITO_DOMAIN}/logout"
REDIRECT_URI = ssm.get_parameter(Name="/auth/redirect-uri", WithDecryption=True)["Parameter"]["Value"]
API_GATEWAY_URI = ssm.get_parameter(Name="/auth/api-gateway-uri", WithDecryption=True)["Parameter"]["Value"]
FRONTEND_URL = ssm.get_parameter(Name="/auth/frontend-url", WithDescryption=True)["Parameter"]["Value"]

session = boto3.session.Session()
client = session.client(
    service_name='secretsmanager',
    region_name=region_name
)

try:
    get_secret_value_response = client.get_secret_value(
        SecretId=secret_name
    )
except ClientError as e:
    # For a list of exceptions thrown, see
    # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
    raise e


CLIENT_SECRET = get_secret_value_response['SecretString']



def lambda_handler(event, context):
    path = event["rawPath"]
    
    if path == "/login":
        return login()
    elif path == "/authorize":
        return authorize(event)
    elif path == "/logout":
        return logout()
    else:
        return {"statusCode": 404, "body": json.dumps({"error": "Invalid route"})}

# Login: Redirect users to Cognito
def login():
    auth_url = (
        f"{AUTHORIZATION_URL}?client_id={CLIENT_ID}"
        f"&response_type=code&scope=email+openid+phone&redirect_uri={REDIRECT_URI}"
    )
    return {
        "statusCode": 302,
        "headers": {"Location": auth_url}
    }

# Authorize: Handle Cognito callback, exchange code for token
def authorize(event):
    query_params = event.get("queryStringParameters", {})
    code = query_params.get("code")

    if not code:
        return {"statusCode": 400, "body": json.dumps({"error": "Authorization code not found"})}

    # Exchange code for tokens
    oauth = OAuth2Session(client_id=CLIENT_ID, client_secret=CLIENT_SECRET, redirect_uri=REDIRECT_URI)
    token = oauth.fetch_token(
        TOKEN_URL,
        authorization_response=f"{REDIRECT_URI}?code={code}",
        code=code
    )

    # Get user info
    headers = {"Authorization": f"Bearer {token['access_token']}"}
    user_info = requests.get(USERINFO_URL, headers=headers).json()
    
    return {
        "statusCode": 302,
        "headers": {
            "Location": f"{FRONTEND_URL}?token={token['id_token']}"
        }
    }

# Logout: Redirect user to Cognito logout page
def logout():
    logout_redirect_uri = API_GATEWAY_URI
    logout_url = f"{LOGOUT_URL}?client_id={CLIENT_ID}&logout_uri={logout_redirect_uri}"

    return {
        "statusCode": 302,
        "headers": {"Location": logout_url}
    }
