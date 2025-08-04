import json
import logging
import os
import decimal
import uuid
import datetime
import base64

import boto3

s3 = boto3.client('s3')
sqs = boto3.client('sqs')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['DYNAMODB_TABLE'])
image_bucket_name = os.environ['IMAGE_BUCKET_NAME']
completed_queue_url = os.environ['COMPLETED_QUEUE_URL']
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def getDaysSinceEpoch():
    """Calculates the number of full days since the Unix epoch (1970-01-01) in UTC."""
    # Get the current time as a timezone-aware object in UTC
    current_time_utc = datetime.datetime.now(datetime.timezone.utc)
    
    # Define the Unix epoch as a timezone-aware object in UTC
    epoch_utc = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
    
    # Calculate the difference in days
    days_since_epoch = (current_time_utc - epoch_utc).days
    
    return days_since_epoch


def receivelprdata(event, context):
    logger.info(f"Received event: {json.dumps(event)}")

    processed_item_guids = []

    for record in event['Records']:
        # The message body from S3 notification is a string, so it needs to be parsed as JSON
        s3_notification = json.loads(record['body'])
        
        # Check to see if the s3 records exist
        if 'Records' not in s3_notification:
            logger.info(f"No files found in S3 event notification.")
            return {
                'statusCode': 200,
                'body': json.dumps('Successfully processed S3 event(s).')
            }

        # S3 notifications can contain multiple records
        for s3_record in s3_notification['Records']:
            bucket_name = s3_record['s3']['bucket']['name']
            object_key = s3_record['s3']['object']['key']

            logger.info(f"Processing file {object_key} from bucket {bucket_name}")

            try:
                s3_object = s3.get_object(Bucket=bucket_name, Key=object_key)
                file_content = s3_object['Body'].read().decode('utf-8')
                # 1. Remove trailing comma, being mindful of whitespace
                # strip() removes leading/trailing whitespace.
                file_content = file_content.strip()
                if file_content.endswith(','):
                    file_content = file_content[:-1]

                # 2. Prepend '[' and append ']' to make it a valid JSON array string
                json_array_string = '[' + file_content + ']'

                # 3. Parse the modified string
                data = json.loads(json_array_string, parse_float=decimal.Decimal)
                
                logger.info(f"File content: {json.dumps(data, default=str)}")

                for plate_data in data:
                    plate_crop_jpeg_url = None
                    if plate_data.get('best_plate', {}).get('plate_crop_jpeg'):
                        try:
                            plate_image_data = base64.b64decode(plate_data['best_plate']['plate_crop_jpeg'])
                            plate_image_key = f"plate_images/{str(uuid.uuid4())}.jpg"
                            s3.put_object(
                                Bucket=image_bucket_name,
                                Key=plate_image_key,
                                Body=plate_image_data,
                                ContentType='image/jpeg'
                            )
                            plate_crop_jpeg_url = f"https://{image_bucket_name}.s3.amazonaws.com/{plate_image_key}"
                        except (base64.binascii.Error, TypeError) as e:
                            logger.error(f"Error decoding or uploading plate_crop_jpeg: {e}")

                    vehicle_crop_jpeg_url = None
                    if plate_data.get('vehicle_crop_jpeg'):
                        try:
                            vehicle_image_data = base64.b64decode(plate_data['vehicle_crop_jpeg'])
                            vehicle_image_key = f"vehicle_images/{str(uuid.uuid4())}.jpg"
                            s3.put_object(
                                Bucket=image_bucket_name,
                                Key=vehicle_image_key,
                                Body=vehicle_image_data,
                                ContentType='image/jpeg'
                            )
                            vehicle_crop_jpeg_url = f"https://{image_bucket_name}.s3.amazonaws.com/{vehicle_image_key}"
                        except (base64.binascii.Error, TypeError) as e:
                            logger.error(f"Error decoding or uploading vehicle_crop_jpeg: {e}")

                    item_guid = str(uuid.uuid4())
                    item = {
                        'plate_read_id': item_guid,
                        'plate_read_timestamp': plate_data.get('epoch_start'),
                        'epoch_start': plate_data.get('epoch_start'),
                        'best_plate_number': plate_data.get('best_plate_number'),
                        'best_confidence': plate_data.get('best_confidence'),
                        'candidates': plate_data.get('candidates'),
                        'best_region': plate_data.get('best_region'),
                        'vehicle': plate_data.get('vehicle'),
                        'days_since_epoch': getDaysSinceEpoch(),
                        'plate_crop_jpeg_url': plate_crop_jpeg_url,
                        'vehicle_crop_jpeg_url': vehicle_crop_jpeg_url
                    }
                    
                    # Safely get camera_label
                    if 'web_server_config' in plate_data and 'camera_label' in plate_data['web_server_config']:
                        item['camera_label'] = plate_data['web_server_config']['camera_label']

                    # Add TTL of 60 days from now
                    ttl_timestamp = int((datetime.datetime.now() + datetime.timedelta(days=60)).timestamp())
                    item['ttl'] = ttl_timestamp

                    # Remove keys with None values before inserting into DynamoDB
                    item_to_insert = {k: v for k, v in item.items() if v is not None}

                    #logger.info(f"Putting item in DynamoDB: {json.dumps(item_to_insert, default=str)}")
                    table.put_item(Item=item_to_insert)
                    processed_item_guids.append(item_guid)

                
                
            except Exception as e:
                logger.error(f"Error processing file {object_key}: {e}")
                # Depending on the use case, you might want to handle this differently
                # For example, move the message to a Dead Letter Queue (DLQ)
                raise e

    if processed_item_guids:
        try:
            message_body = json.dumps(processed_item_guids)
            sqs.send_message(
                QueueUrl=completed_queue_url,
                MessageBody=message_body,
                DelaySeconds=30,
            )
            logger.info(f"Sent {len(processed_item_guids)} item GUIDs to completed queue.")
        except Exception as e:
            logger.error(f"Error sending message to completed queue: {e}")
            raise e

    return {
        'statusCode': 200,
        'body': json.dumps('Successfully processed S3 event(s).')
    }
