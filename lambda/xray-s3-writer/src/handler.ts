import { Context } from "aws-lambda";
import { S3Client, PutObjectCommand } from "@aws-sdk/client-s3";

const s3Client = new S3Client({});
const DOG_BUCKET_NAME = process.env.DOG_BUCKET_NAME;

interface DogWriteEvent {
  imageUrl: string;
  fetchedAt: string;
}

interface DogWriteResult {
  imageKey: string;
  metadataKey: string;
  bucket: string;
}

async function downloadImage(url: string): Promise<Buffer> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to download image from ${url}: ${response.status}`);
  }
  return Buffer.from(await response.arrayBuffer());
}

export const handler = async (
  event: DogWriteEvent,
  _context: Context
): Promise<DogWriteResult> => {
  if (!DOG_BUCKET_NAME) {
    throw new Error("DOG_BUCKET_NAME env var is not set");
  }

  const { imageUrl, fetchedAt } = event;
  console.log(`Processing dog image URL: ${imageUrl}`);

  const urlPath = new URL(imageUrl).pathname;
  const ext = urlPath.split(".").pop() ?? "jpg";
  const timestamp = new Date(fetchedAt).getTime();

  const imageBytes = await downloadImage(imageUrl);
  console.log(`Downloaded ${imageBytes.length} bytes`);

  const imageKey = `dogs/${timestamp}.${ext}`;
  await s3Client.send(
    new PutObjectCommand({
      Bucket: DOG_BUCKET_NAME,
      Key: imageKey,
      Body: imageBytes,
      ContentType: `image/${ext}`,
      Metadata: { "source-url": imageUrl, "fetched-at": fetchedAt },
    })
  );
  console.log(`Stored image at s3://${DOG_BUCKET_NAME}/${imageKey}`);

  const metadataKey = `dogs/${timestamp}.json`;
  await s3Client.send(
    new PutObjectCommand({
      Bucket: DOG_BUCKET_NAME,
      Key: metadataKey,
      Body: JSON.stringify({
        imageUrl,
        fetchedAt,
        s3ImageKey: imageKey,
        s3Bucket: DOG_BUCKET_NAME,
        processedAt: new Date().toISOString(),
        imageSizeBytes: imageBytes.length,
      }),
      ContentType: "application/json",
    })
  );
  console.log(`Stored metadata at s3://${DOG_BUCKET_NAME}/${metadataKey}`);

  return { imageKey, metadataKey, bucket: DOG_BUCKET_NAME };
};
