import json
import logging
import os
import boto3
import datetime
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource('dynamodb')
lpr_table = dynamodb.Table(os.environ['LPR_DYNAMODB_TABLE'])
valet_table = dynamodb.Table(os.environ['VALET_DYNAMODB_TABLE'])
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

def clean_levenshtein(s1, s2):
    s1 = s1.lower().replace('-', '').replace(' ', '')
    s2 = s2.lower().replace('-', '').replace(' ', '')
    return levenshtein(s1, s2)

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

def verifylprdata(event, context):
    logger.info(f"Received event: {json.dumps(event)}")

    for record in event['Records']:
        try:
            item_guids = json.loads(record['body'])
            logger.info(f"Processing GUIDs: {item_guids}")

            for guid in item_guids:
                # Query DynamoDB to get the item using the plate_read_id
                response = lpr_table.query(
                    KeyConditionExpression=Key('plate_read_id').eq(guid)
                )

                if response['Items']:
                    # Assuming plate_read_id is unique, so we take the first item
                    item = response['Items'][0]
                    plate_read_id = item.get('plate_read_id')
                    plate_read_timestamp = item.get('plate_read_timestamp')
                    best_confidence = item.get('best_confidence')
                    best_plate_number = item.get('best_plate_number')
                    best_region = item.get('best_region')
                    camera_label = item.get('camera_label')
                    days_since_epoch = item.get('days_since_epoch')
                    plate_crop_jpeg_url = item.get('plate_crop_jpeg_url')
                    vehicle_crop_jpeg_url = item.get('vehicle_crop_jpeg_url')

                    logger.info(f"Verifying plate_read_id: {plate_read_id} plate: {best_plate_number} Location: {camera_label}")

                    if camera_label == '900 Garage Gate Entrance':
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

                        if not best_plate_number:
                            logger.info("No 'best_plate_number' in the item to check.")
                            return

                        # Loop through registered plates and check for a match.
                        is_registered = False
                        for plate in registered_plates:
                            
                            if clean_levenshtein(plate, best_plate_number) <= 1:
                                is_registered = True

                            if is_registered:
                                logger.info(f"MATCH FOUND: Detected plate '{best_plate_number}' matches registered plate '{plate}'.")
                                # Here you would add logic for what to do on a match,
                                # like opening a gate or sending a notification.
                                # For this example, we'll just log and break.
                                break
                        
                        if is_registered == False:
                            logger.info(f"PLATE NOT FOUND IN REGISTERED VEHICLES: Detected plate '{best_plate_number}'.")

                            # Get all plates from DynamoDB that happened in the previous ten minutes.
                            ten_minutes_in_ms = 10 * 60 * 1000
                            start_timestamp = plate_read_timestamp - ten_minutes_in_ms

                            # Query for the current day
                            query_response_today = lpr_table.query(
                                IndexName='DaysSinceEpochIndex',
                                KeyConditionExpression=Key('days_since_epoch').eq(days_since_epoch) & Key('plate_read_timestamp').between(start_timestamp, plate_read_timestamp)
                            )

                            # Query for the previous day in case the 10-minute window crosses midnight
                            previous_days_since_epoch = days_since_epoch - 1
                            query_response_yesterday = lpr_table.query(
                                IndexName='DaysSinceEpochIndex',
                                KeyConditionExpression=Key('days_since_epoch').eq(previous_days_since_epoch) & Key('plate_read_timestamp').between(start_timestamp, plate_read_timestamp)
                            )

                            recent_plates = query_response_today.get('Items', []) + query_response_yesterday.get('Items', [])
                            logger.info(f"Found {len(recent_plates)} recent plates for {best_plate_number} in the last 10 minutes.")

                            # Check if any of the recent plates were at the valet.
                            went_through_valet = False
                            for p in recent_plates:
                                lev_distance_result = levenshtein(p.get('best_plate_number'), best_plate_number)
                                if p.get('camera_label') == '900 Valet' and lev_distance_result <= 1:
                                    went_through_valet = True
                                    logger.info(f"MATCH FOUND: Unregistered plate '{best_plate_number}' was seen at '900 Valet'.")
                                    break
                            
                            if went_through_valet:
                                # If a plate went through valet and is_registered is FALSE, it should be generating revenue.
                                logger.info(f"Plate '{best_plate_number}' is generating revenue.")
                                
                                #Insert the plate into the valet_table with all of the information we have on it.
                                item = {
                                    'plate_read_id': plate_read_id,
                                    'best_plate_number': best_plate_number,
                                    'plate_read_timestamp': plate_read_timestamp,
                                    'best_confidence': best_confidence,
                                    'best_region': best_region,
                                    'days_since_epoch': getDaysSinceEpoch(),
                                    'plate_crop_jpeg_url': plate_crop_jpeg_url,
                                    'vehicle_crop_jpeg_url': vehicle_crop_jpeg_url
                                }

                                # Remove keys with None values before inserting into DynamoDB
                                item_to_insert = {k: v for k, v in item.items() if v is not None}

                                # Insert the plate into the valet table so we can track when it exits and how much money they owe.
                                valet_table.put_item(Item=item_to_insert)
                            else:
                                # If a plate did not go through valet and is_registered is FALSE, it should be sent to security.
                                logger.info(f"Plate '{best_plate_number}' NOT seen at valet. Sending to security.")

                    if camera_label == '900 Garage Gate Exit':
                        logger.info("Plate seen exiting.")
                        
                        #TODO: Download all plates from the valet_table for the last 30 days. Use getDaysSinceEpoch and go back 30 
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