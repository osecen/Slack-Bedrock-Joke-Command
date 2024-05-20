import boto3
import json
import logging
import os
from base64 import b64decode
from urllib.parse import parse_qs

bucket_name = 'tell-me-a-joke-1'
object_key = 'jokes.txt'
ENCRYPTED_EXPECTED_TOKEN = os.environ['kmsEncryptedToken']

bedrock_client = boto3.client(service_name="bedrock-runtime", region_name="us-east-1")
model_id = "anthropic.claude-3-sonnet-20240229-v1:0"
logger = logging.getLogger()
logger.setLevel(logging.INFO)
s3 = boto3.client('s3')

def get_last_30_jokes():
    try:
        response = s3.get_object(Bucket=bucket_name, Key=object_key)
        content = response['Body'].read().decode('utf-8')
        jokes = content.split('\n')
        # Get the last 30 jokes, ensuring no empty lines are included
        last_30_jokes = [joke for joke in jokes if joke][-30:]
        return last_30_jokes
    except Exception as err:
        logger.error("Error retrieving jokes from S3: %s", err)
        return []


def append_string_to_s3_file(string_to_append):
    response = s3.get_object(Bucket=bucket_name, Key=object_key)
    existing_content = response['Body'].read().decode('utf-8')
    updated_content = string_to_append + '\n' + existing_content
    s3.put_object(Bucket=bucket_name, Key=object_key, Body=updated_content.encode('utf-8'))

def respond(err, res=None):
    return {
        'statusCode': '400' if err else '200',
        'body': err.message if err else json.dumps(res).encode('utf8'),
        'headers': {'Content-Type': 'application/json'},
    }

def get_a_joke():
    try:
        last_30_jokes = get_last_30_jokes()
        context_jokes = " ".join(last_30_jokes)  # Combine jokes into a single string

        # Model invocation with context to avoid last 30 jokes
        response = bedrock_client.invoke_model(
            modelId=model_id,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": f"Please tell me a new joke that is not any of these: {context_jokes}. You are a smart jokester. Please return the joke as a JSON object with joke field as the joke itself and answer as the answer to the joke, stringify the JSON. Do not return the answer in the joke field."}]}
                ],
            }),
        )

        result = json.loads(response.get("body").read())
        json_string = result.get("content", [])[0]['text']
        parsed_joke = json.loads(json_string)
        joke = parsed_joke['joke']
        append_string_to_s3_file(json_string)
        return joke

    except Exception as err:
        logger.error("Couldn't invoke Claude 3 Sonnet. Error: %s", err)
        return ''

def respond_to_joke(user_response, username):
    try:
        response = s3.get_object(Bucket=bucket_name, Key=object_key)
        existing_content_first_line = response['Body'].readline().decode('utf-8').strip()
        prompt = (f'You are a smart jokester and you already asked the joke given next as a json object, joke being the joke and answer being the answer. {existing_content_first_line} '
                  f'Now the user responded back to your joke trying to figure out the answer to your joke. The name of the user is {username} and their response is {user_response}. '
                  f'If the user is able to figure out the answer, respond with affirmation, congratulate the user and include the original answer. Again, include the answer only if the user responds close enough to the actual answer. '
                  'If the user response is not accurate, respond with humor, creativity, and encourage them to try again, do not include the actual answer in the response. '
                  'For example, you can say - great idea, try again. '
                  'Keep your response under 30 words and respond directly as if you are talking to the user, do not include the joke or the user response in your response.')

        response = bedrock_client.invoke_model(
            modelId=model_id,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            }),
        )

        result = json.loads(response.get("body").read())
        return result.get("content", [])[0]['text']

    except Exception as err:
        logger.error("Couldn't invoke Claude 3 Sonnet. Error: %s", err)
        return ''

def lambda_handler(event, context):
    try:
        body = b64decode(event['body'])
        params = parse_qs(body)
        cleaned_params = {key.decode(): value[0].decode() for key, value in params.items()}

        if ENCRYPTED_EXPECTED_TOKEN != cleaned_params['token']:
            logger.error("Request token does not match expected")
            return respond(Exception('Invalid request token'))

        if 'text' in cleaned_params and cleaned_params['text']:
            return_result = respond_to_joke(cleaned_params['text'], cleaned_params['user_name'])
        else:
            return_result = get_a_joke()

        return_result = return_result.replace('\n', '')
        return respond(None, return_result)

    except Exception as err:
        logger.error("Error handling the event: %s", err)
        return respond(err)
