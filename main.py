import base64
import json
import os
import re

import anthropic
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

app = FastAPI()

FOOD_DIR = os.path.join(os.path.dirname(__file__), "food")


@app.get("/", response_class=HTMLResponse)
def read_root():
    with open(os.path.join(os.path.dirname(__file__), "index.html"), "r", encoding="utf-8") as f:
        return f.read()


# Endpoint 1: List all available foods
@app.get("/foods")
def list_all_foods():
    files = [f for f in os.listdir(FOOD_DIR) if f.endswith(".json")]
    food_names = [f.replace(".json", "") for f in files]
    return {"available_foods": food_names}


# Endpoint 2: Get nutritional data for a specific food
@app.get("/foods/{food_name}")
def get_food_nutrition(food_name: str):
    file_path = os.path.join(FOOD_DIR, f"{food_name}.json")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Food not found in database")

    with open(file_path, "r", encoding="utf-8") as file:
        food_data = json.load(file)

    return food_data


# Endpoint 3: Upload a photo of a nutrition label and create a new food JSON
@app.post("/foods/upload")
async def upload_food_photo(
    food_name: str = Form(...),
    photo: UploadFile = File(...),
):
    # Validate file type
    if not photo.content_type or not photo.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    # Check food name doesn't have path traversal
    safe_name = re.sub(r"[^\w\-]", "", food_name)
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid food name")

    file_path = os.path.join(FOOD_DIR, f"{safe_name}.json")
    if os.path.exists(file_path):
        raise HTTPException(status_code=409, detail=f"'{safe_name}' already exists")

    # Read and encode image
    image_bytes = await photo.read()
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    media_type = photo.content_type  # e.g. "image/jpeg"

    # Ask Claude to extract nutrition info from the label
    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "This is a nutrition label. Extract all the information and return it "
                            "as a JSON object with this exact structure — no extra text, just the JSON:\n\n"
                            '{\n'
                            '  "tamaño_porcion": "<serving size with unit>",\n'
                            '  "calorias_porcion": "<calories per serving>",\n'
                            '  "nutrientes": [\n'
                            '    {\n'
                            '      "nutriente": "<nutrient name>",\n'
                            '      "cantidad_porcion": "<amount per serving>",\n'
                            '      "cantidad_100g_ml": "<amount per 100g/ml or null>",\n'
                            '      "porcentaje_vd": "<% daily value or null>"\n'
                            '    }\n'
                            '  ]\n'
                            "}\n\n"
                            "Keep nutrient names in the same language as the label. "
                            "Use null for missing values."
                        ),
                    },
                ],
            }
        ],
    )

    raw = response.content[0].text.strip()

    # Strip markdown code fences if Claude wrapped the JSON
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw.strip())

    try:
        food_data = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=502,
            detail="Claude could not extract valid JSON from the label. Try a clearer photo.",
        )

    # Save to food/
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(food_data, f, ensure_ascii=False, indent=2)

    return {"message": f"'{safe_name}' saved successfully", "data": food_data}
