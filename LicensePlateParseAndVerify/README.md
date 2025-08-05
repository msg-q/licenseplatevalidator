# License Plate Parse and Verify Service

This service is responsible for processing license plate data received from an S3 bucket, parsing it, storing it in DynamoDB, and then verifying the license plates based on a set of rules.

## Architecture

The service is built using the Serverless Framework and consists of the following AWS resources:

*   **AWS Lambda Functions:**
    *   `processlprdata`: Triggered by an SQS message, this function reads license plate data from an S3 bucket, parses it, and stores it in the `LprDataTable`.
    *   `verifylprdata`: Triggered by an SQS message from the `LprParseAndStoreCompletedQueue`, this function verifies the license plate against a list of registered plates and business logic.

*   **Amazon SQS Queues:**
    *   `lpr-processing-queue`: Receives notifications from S3 when a new license plate data file is uploaded.
    *   `lpr-parse-and-store-completed`: Receives a message after the `processlprdata` function has successfully processed a license plate.

*   **Amazon DynamoDB Tables:**
    *   `LprDataTable`: Stores the parsed license plate data.
    *   `ValetRevenueTracking`: Stores information about valet-parked vehicles to track revenue.

*   **Amazon S3 Bucket:**
    *   `LprImageBucket`: Stores images of the license plates and vehicles.

## Operational Flow

1.  A new license plate data file is uploaded to the `lpringestionservice-dev-s3bucket-q9nhy6tnerz6` S3 bucket.
2.  S3 sends a notification to the `lpr-processing-queue` SQS queue.
3.  The `processlprdata` Lambda function is triggered by the SQS message.
4.  The function reads the file from S3, parses the license plate data, and stores it in the `LprDataTable` DynamoDB table. It also extracts and stores any associated images in the `LprImageBucket` S3 bucket.
5.  Upon successful processing, a message containing the `plate_read_id` is sent to the `lpr-parse-and-store-completed` SQS queue.
6.  The `verifylprdata` Lambda function is triggered by the message in the `lpr-parse-and-store-completed` queue.
7.  The function retrieves the full data from the `LprDataTable` using the `plate_read_id`.
8.  The license plate is then verified based on the following logic:
    *   If the camera label is `900 Garage Gate Entrance`:
        *   The license plate is checked against a list of registered plates in `Registered_License_Plates.txt`.
        *   If it's not a registered plate, the system checks if the vehicle was seen at the `900 Valet` location within the last 10 minutes.
        *   If it was seen at the valet, the plate is added to the `ValetRevenueTracking` table.
        *   If it was not seen at the valet, a security alert is logged.
    *   If the camera label is `900 Garage Gate Exit`:
        *   The system checks if the exiting plate is in the `ValetRevenueTracking` table as an unpaid vehicle.
        *   If a match is found, the system calculates the parking fee based on the duration of the stay and updates the record with the revenue received.

## Setup

To deploy this service, you will need to have the Serverless Framework installed and configured with your AWS credentials.

1.  Install the project dependencies:
    ```
    npm install
    ```
2.  Deploy the service:
    ```
    serverless deploy