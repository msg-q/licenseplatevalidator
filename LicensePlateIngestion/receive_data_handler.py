import json
import boto3
import os

firehose_name = os.environ.get('FIREHOSE_NAME', 'LicensePlateDataStream')
firehose = boto3.client('firehose')

def receivelprdata(event, context):
    try:
        data = json.loads(event['body'])
        firehose.put_record(
            DeliveryStreamName=firehose_name,
            Record={
                'Data': json.dumps(data) + ',\n'
            }
        )
        body = {
            "message": "Data sent to firehose",
        }
        response = {"statusCode": 200, "body": json.dumps(body)}
    except Exception as e:
        response = {"statusCode": 500, "body": json.dumps({"error": str(e)})}


    return response