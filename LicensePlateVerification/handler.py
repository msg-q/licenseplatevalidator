import json
import logging
import os
import decimal
import uuid
import datetime

import boto3

s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['DYNAMODB_TABLE'])
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

def levenshtein(s1, s2):
    if len(s1) < len(s2):
        return levenshtein(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def checkLicensePlateInfo(item):
    # logger.info("Checking License Plate Info")

    # Check if the camera is the garage entrance camera
    if item.get('camera_label') == '900 Garage Gate Entrance':
        # logger.info("Plate at Entrance - checking against registered plates.")
        # Load registered license plates from the file.
        try:
            # Assuming the text file is in the same directory as the handler.
            script_dir = os.path.dirname(__file__)
            file_path = os.path.join(script_dir, 'Registered_License_Plates.txt')
            with open(file_path, 'r') as f:
                registered_plates = [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            logger.error("Registered_License_Plates.txt not found.")
            return

        best_plate_number = item.get('best_plate_number')
        if not best_plate_number:
            logger.info("No 'best_plate_number' in the item to check.")
            return

        # Normalize the detected plate number
        cleaned_best_plate = best_plate_number.lower().replace('-', '').replace(' ', '')

        # Loop through registered plates and check for a match.
        is_registered = False
        for plate in registered_plates:
            # Normalize the registered plate number
            cleaned_plate = plate.lower().replace('-', '').replace(' ', '')
            
            if levenshtein(cleaned_plate, cleaned_best_plate) <= 1:
                is_registered = True

            if is_registered:
                logger.info(f"MATCH FOUND: Detected plate '{best_plate_number}' matches registered plate '{plate}'.")
                # Here you would add logic for what to do on a match,
                # like opening a gate or sending a notification.
                # For this example, we'll just log and break.
                break
        
        if is_registered == False:
            logger.info(f"PLATE NOT FOUND IN REGISTERED VEHICLES: Detected plate '{best_plate_number}'.")

            #TODO: Get all plates from DynamoDB that happened in the previous ten minutes.

            #TODO: Filter those plates by camera_label = 900 Valet

            #TODO: If a plate went through valet and is_registered == FALSE, then it should be generating revenue

            #TODO: If a plate went did not go through valet and is_registered == FALSE, then it should be sent to security

def receivelprdata(event, context):
    logger.info(f"Received event: {json.dumps(event)}")

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
                    item = {
                        'plate_read_id': str(uuid.uuid4()),
                        'plate_read_timestamp': plate_data.get('epoch_start'),
                        'epoch_start': plate_data.get('epoch_start'),
                        'best_plate_number': plate_data.get('best_plate_number'),
                        'best_confidence': plate_data.get('best_confidence'),
                        'candidates': plate_data.get('candidates'),
                        'best_region': plate_data.get('best_region'),
                        'vehicle': plate_data.get('vehicle'),
                        'days_since_epoch': getDaysSinceEpoch()
                    }
                    # Safely get camera_label
                    if 'web_server_config' in plate_data and 'camera_label' in plate_data['web_server_config']:
                        item['camera_label'] = plate_data['web_server_config']['camera_label']

                    # Add TTL of 60 days from now
                    ttl_timestamp = int((datetime.datetime.now() + datetime.timedelta(days=60)).timestamp())
                    item['ttl'] = ttl_timestamp

                    # Remove keys with None values before inserting into DynamoDB
                    item_to_insert = {k: v for k, v in item.items() if v is not None}
                    
                    checkLicensePlateInfo(item_to_insert)

                    #logger.info(f"Putting item in DynamoDB: {json.dumps(item_to_insert, default=str)}")
                    table.put_item(Item=item_to_insert)

                
                
            except Exception as e:
                logger.error(f"Error processing file {object_key}: {e}")
                # Depending on the use case, you might want to handle this differently
                # For example, move the message to a Dead Letter Queue (DLQ)
                raise e

    return {
        'statusCode': 200,
        'body': json.dumps('Successfully processed S3 event(s).')
    }
