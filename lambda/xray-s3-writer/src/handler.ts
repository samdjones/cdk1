import { SNSEvent, SNSMessage, Context } from "aws-lambda";
import { S3Client, PutObjectCommand } from "@aws-sdk/client-s3";

const s3Client = new S3Client({});
const DOG_BUCKET_NAME = process.env.DOG_BUCKET_NAME;

interface DogSNSPayload {
  imageUrl: string;
  fetchedAt: string;
}

async function downloadImage(url: string): Promise<Buffer> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to download image from ${url}: ${response.status}`);
  }
  const arrayBuffer = await response.arrayBuffer();
  return Buffer.from(arrayBuffer);
}

async function processMessage(message: SNSMessage): Promise<void> {
  if (!DOG_BUCKET_NAME) {
    throw new Error("DOG_BUCKET_NAME env var is not set");
  }

  const payload: DogSNSPayload = JSON.parse(message.Message) as DogSNSPayload;
  const { imageUrl, fetchedAt } = payload;

  console.log(`Processing dog image URL: ${imageUrl}`);

  // Determine file extension from URL
  const urlPath = new URL(imageUrl).pathname;
  const ext = urlPath.split(".").pop() ?? "jpg";
  const timestamp = new Date(fetchedAt).getTime();

  // Download the image bytes
  const imageBytes = await downloadImage(imageUrl);
  console.log(`Downloaded ${imageBytes.length} bytes`);

  // Store the image in S3
  const imageKey = `dogs/${timestamp}.${ext}`;
  await s3Client.send(
    new PutObjectCommand({
      Bucket: DOG_BUCKET_NAME,
      Key: imageKey,
      Body: imageBytes,
      ContentType: `image/${ext}`,
      Metadata: {
        "source-url": imageUrl,
        "fetched-at": fetchedAt,
      },
    })
  );
  console.log(`Stored image at s3://${DOG_BUCKET_NAME}/${imageKey}`);

  // Write metadata JSON
  const metadataKey = `dogs/${timestamp}.json`;
  const metadata = {
    imageUrl,
    fetchedAt,
    s3ImageKey: imageKey,
    s3Bucket: DOG_BUCKET_NAME,
    processedAt: new Date().toISOString(),
    imageSizeBytes: imageBytes.length,
  };

  await s3Client.send(
    new PutObjectCommand({
      Bucket: DOG_BUCKET_NAME,
      Key: metadataKey,
      Body: JSON.stringify(metadata, null, 2),
      ContentType: "application/json",
    })
  );
  console.log(`Stored metadata at s3://${DOG_BUCKET_NAME}/${metadataKey}`);
}

export const handler = async (event: SNSEvent, _context: Context): Promise<void> => {
  console.log(`Processing ${event.Records.length} SNS record(s)`);

  await Promise.all(event.Records.map((record) => processMessage(record.Sns)));

  console.log("All records processed successfully");
};
