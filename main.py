from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from google import genai
from google.genai import types
from google.cloud import storage
import os
import uuid

# ---- [1] GCP 서비스 계정 키 환경변수(문자열) → 임시 파일로 저장 ----
json_data = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
if json_data:
    # Vercel/클라우드 환경에서는 환경변수에서 받은 JSON 키를 임시 파일로 저장
    with open("/tmp/gcp_key.json", "w") as f:
        f.write(json_data)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/tmp/gcp_key.json"

# ---- [2] Gemini API 키 환경변수 (꼭 시크릿으로 관리) ----
API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_DEFAULT_API_KEY")
client = genai.Client(api_key=API_KEY)

# ---- [3] GCS 버킷 정보 ----
BUCKET_NAME = "map-of-memory-bucket"
IMAGE_DIR = "ai-images"

app = FastAPI()

class PostRequest(BaseModel):
    title: str
    content: str

def upload_image_to_gcs(image_bytes, filename):
    storage_client = storage.Client()
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(f"{IMAGE_DIR}/{filename}")
    blob.upload_from_string(image_bytes, content_type="image/png")
    return blob.public_url

def generate_gemini_image(title, content):
    prompt = (f"Create an artistic 3d rendered image based on the following post.\n"
    f"Title: {title}\nContent: {content}\n"
    f"Do not include any text, captions, letters, or visible writing in the image. Only generate the illustration itself, with no words.")
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash-preview-image-generation",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=['IMAGE', 'TEXT']
            )
        )
    except Exception as e:
        print("Gemini API 호출 예외:", e)
        return None

    print("Gemini 전체 응답:", response)
    image_bytes = None
    try:
        for c in response.candidates:
            for part in c.content.parts:
                print("part:", part)
                if hasattr(part, 'inline_data') and part.inline_data is not None:
                    image_bytes = part.inline_data.data
    except Exception as e:
        print("Gemini 응답 파싱 예외:", e)
        return None

    return image_bytes

@app.post("/generate-image")
def generate_image_post(req: PostRequest):
    image_bytes = generate_gemini_image(req.title, req.content)
    if not image_bytes:
        return JSONResponse({"error": "Failed to generate image from Gemini"}, status_code=500)

    filename = f"{uuid.uuid4()}.png"
    public_url = upload_image_to_gcs(image_bytes, filename)

    return JSONResponse({"image_url": public_url})