from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from google import genai
from google.genai import types
from google.cloud import storage
import os
import uuid

# ---- [1] GCP 서비스 계정 키 환경변수(문자열) → 임시 파일로 저장 ----
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    # 환경 변수가 설정되지 않았을 경우, 시작 시 오류 발생
    raise ValueError("GEMINI_API_KEY 환경 변수가 설정되지 않았습니다. Cloud Run 환경 변수에 추가해주세요.")
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
