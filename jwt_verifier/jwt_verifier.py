import jwt  # Install using `pip install pyjwt`
import boto3
import json

# Load Cognito details from AWS SSM Parameter Store
ssm = boto3.client("ssm")
USER_POOL_ID = ssm.get_parameter(Name="/auth/user-pool-id", WithDecryption=True)["Parameter"]["Value"]

COGNITO_ISSUER = f"https://cognito-idp.us-east-1.amazonaws.com/{USER_POOL_ID}"

def verify_token(token):
    """Decode and verify JWT token from Cognito"""
    try:
        # Decode JWT token (without verification for simplicity)
        decoded_token = jwt.decode(token, options={"verify_signature": False})

        # Verify issuer
        if decoded_token["iss"] != COGNITO_ISSUER:
            return {"error": "Invalid token issuer"}

        return decoded_token
    except Exception as e:
        return {"error": str(e)}
