from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from google import genai
from google.genai import types
from google.cloud import storage
import os
import uuid
import httpx # Required for making HTTP requests to Spring backend

# --- [1] Gemini API 키 환경변수 (꼭 시크릿으로 관리 및 필수 설정) ---
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("GEMINI_API_KEY 환경 변수가 설정되지 않았습니다. Cloud Run 환경 변수에 추가해주세요.")
client = genai.Client(api_key=API_KEY)

# --- [2] GCS 버킷 정보 ---
BUCKET_NAME = "map-of-memory-bucket" # 실제 버킷 이름으로 변경하세요.
IMAGE_DIR = "ai-images"

# --- [3] Spring 백엔드 URL 환경 변수 ---
SPRING_BACKEND_URL = os.getenv("SPRING_BACKEND_URL")
if not SPRING_BACKEND_URL:
    raise ValueError("SPRING_BACKEND_URL 환경 변수가 설정되지 않았습니다. Spring 백엔드의 URL을 지정해주세요.")

app = FastAPI()

class PostRequest(BaseModel):
    title: str
    content: str

def upload_image_to_gcs(image_bytes, filename):
    """
    Generates a unique filename for the image and uploads it to Google Cloud Storage.
    Returns the public URL of the uploaded image.
    """
    storage_client = storage.Client()
    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(f"{IMAGE_DIR}/{filename}")
    blob.upload_from_string(image_bytes, content_type="image/png")
    return blob.public_url

def generate_gemini_image(title, content):
    """
    Generates an artistic 3D rendered image using the specified Gemini model.
    The prompt is carefully crafted to avoid text in the image.
    Returns the image bytes on success, None on failure.
    """
    prompt = (f"Create an artistic 3d rendered image based on the following post.\n"
    f"Title: {title}\nContent: {content}\n"
    f"Do not include any text, captions, letters, or visible writing in the image. Only generate the illustration itself, with no words.")
    try:
        # Using the model specified by the user: gemini-2.0-flash-preview-image-generation
        # Keeping response_modalities=['IMAGE', 'TEXT'] as provided, assuming it's supported by this preview model.
        # If 'Multi-modal output is not supported' error reappears, change this to ['IMAGE'].
        response = client.models.generate_content(
            model="gemini-2.0-flash-preview-image-generation",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=['IMAGE', 'TEXT']
            )
        )
    except Exception as e:
        print(f"Gemini API 호출 예외: {e}")
        return None

    print(f"Gemini 전체 응답: {response}")
    image_bytes = None
    try:
        for c in response.candidates:
            for part in c.content.parts:
                print(f"part: {part}")
                if hasattr(part, 'inline_data') and part.inline_data is not None:
                    image_bytes = part.inline_data.data
                    break 
            if image_bytes:
                break 
    except Exception as e:
        print(f"Gemini 응답 파싱 예외: {e}")
        return None

    return image_bytes

async def send_to_spring_backend(image_url: str, jwt_token: str):
    """
    Sends the generated image URL and JWT token to the Spring backend.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": jwt_token 
    }
    payload = {
        "imageUrl": image_url
    }
    
    async with httpx.AsyncClient() as client:
        try:
            print(f"Sending image URL to Spring backend: {SPRING_BACKEND_URL} with payload: {payload} and Authorization: {jwt_token}")
            spring_response = await client.post(SPRING_BACKEND_URL, headers=headers, json=payload, timeout=30.0)
            spring_response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
            print(f"Successfully sent to Spring backend. Response: {spring_response.json()}")
            return spring_response.json()
        except httpx.RequestError as exc:
            print(f"An error occurred while requesting Spring backend: {exc}")
            raise HTTPException(status_code=500, detail=f"Failed to connect to Spring backend: {exc}")
        except httpx.HTTPStatusError as exc:
            print(f"Error response from Spring backend {exc.response.status_code}: {exc.response.text}")
            raise HTTPException(status_code=exc.response.status_code, detail=f"Spring backend returned an error: {exc.response.text}")
        except Exception as e:
            print(f"Unexpected error when sending to Spring backend: {e}")
            raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")


@app.post("/generate-image")
async def generate_image_post(req: PostRequest, request: Request):
    """
    Main endpoint to generate an image and forward its URL with JWT to Spring backend.
    """
    jwt_token = request.headers.get("Authorization")
    if not jwt_token:
        print("Warning: No Authorization header (JWT token) found in the request.")
    
    # [2] Gemini를 통해 이미지 생성
    image_bytes = generate_gemini_image(req.title, req.content)
    if not image_bytes:
        return JSONResponse({"error": "Failed to generate image from Gemini. Check Gemini API logs for details."}, status_code=500)

    # [3] 생성된 이미지를 GCS에 업로드
    filename = f"{uuid.uuid4()}.png"
    public_url = upload_image_to_gcs(image_bytes, filename)
    print(f"Image uploaded to GCS: {public_url}")

    # [4] 이미지 URL과 JWT 토큰을 Spring 백엔드로 전송
    try:
        spring_response_data = await send_to_spring_backend(public_url, jwt_token)
        return JSONResponse({
            "image_url": public_url,
            "spring_backend_response": spring_response_data
        }, status_code=200)
    except HTTPException as http_exc:
        return JSONResponse({"error": http_exc.detail}, status_code=http_exc.status_code)
    except Exception as e:
        return JSONResponse({"error": f"An unexpected error occurred during Spring communication: {e}"}, status_code=500)

