import json
import logging
import os
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['DYNAMODB_TABLE'])
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def verifylprdata(event, context):
    logger.info(f"Received event: {json.dumps(event)}")

    for record in event['Records']:
        try:
            item_guids = json.loads(record['body'])
            logger.info(f"Processing GUIDs: {item_guids}")

            for guid in item_guids:
                # Query DynamoDB to get the item using the plate_read_id
                response = table.query(
                    KeyConditionExpression=Key('plate_read_id').eq(guid)
                )

                if response['Items']:
                    # Assuming plate_read_id is unique, so we take the first item
                    item = response['Items'][0]
                    plate_read_id = item['plate_read_id']
                    plate_read_timestamp = item['plate_read_timestamp']

                    logger.info(f"Verifying item: {plate_read_id}")
                else:
                    logger.warning(f"No item found in DynamoDB for plate_read_id: {guid}")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from SQS message body: {record['body']}. Error: {e}")
        except Exception as e:
            logger.error(f"An error occurred: {e}")
            # Depending on the error, you might want to re-raise it to have the message retried
            # For now, we log and continue to avoid blocking the queue for one bad message.
            pass

    return {
        'statusCode': 200,
        'body': json.dumps('Successfully processed verification messages.')
    }