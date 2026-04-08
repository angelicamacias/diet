import base64
import json
import os
import re

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from github import Github, GithubException

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO", "angelicamacias/diet")
GITHUB_FOLDER = os.getenv("GITHUB_FOLDER", "food")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FOOD_DIR = os.path.join(os.path.dirname(__file__), "food")
TRACKING_DIR = os.path.join(os.path.dirname(__file__), "food_tracking")
ALLOWED_USERS = {"AM", "JC"}
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def push_to_github(filename: str, content: dict) -> dict:
    """Push a JSON file to the configured GitHub repo. Returns status info."""
    if not GITHUB_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="GITHUB_TOKEN is not set in the environment. Check your .env file.",
        )

    g = Github(GITHUB_TOKEN)

    try:
        repo = g.get_repo(GITHUB_REPO)
    except GithubException as e:
        raise HTTPException(
            status_code=502,
            detail=f"Could not access repo '{GITHUB_REPO}': {e.data.get('message', str(e))}",
        )

    path = f"{GITHUB_FOLDER}/{filename}.json"
    file_content = json.dumps(content, ensure_ascii=False, indent=2)

    try:
        existing = repo.get_contents(path)
        result = repo.update_file(
            path=path,
            message=f"Update nutrition data: {filename}",
            content=file_content,
            sha=existing.sha,
        )
        action = "updated"
    except GithubException:
        result = repo.create_file(
            path=path,
            message=f"Add nutrition data: {filename}",
            content=file_content,
        )
        action = "created"

    commit_url = result["commit"].html_url
    return {"action": action, "path": path, "commit_url": commit_url}


def delete_from_github(filename: str) -> dict:
    """Delete a JSON file from the configured GitHub repo."""
    if not GITHUB_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="GITHUB_TOKEN is not set in the environment.",
        )

    g = Github(GITHUB_TOKEN)

    try:
        repo = g.get_repo(GITHUB_REPO)
    except GithubException as e:
        raise HTTPException(
            status_code=502,
            detail=f"Could not access repo '{GITHUB_REPO}': {e.data.get('message', str(e))}",
        )

    path = f"{GITHUB_FOLDER}/{filename}.json"

    try:
        existing = repo.get_contents(path)
        result = repo.delete_file(
            path=path,
            message=f"Delete nutrition data: {filename}",
            sha=existing.sha,
        )
        return {"action": "deleted", "path": path, "commit_url": result["commit"].html_url}
    except GithubException:
        return {"action": "skipped", "path": path, "note": "File not found in GitHub"}


@app.get("/", response_class=HTMLResponse)
def read_root():
    index_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/foods")
def list_all_foods():
    """List all available foods in the local food/ directory."""
    os.makedirs(FOOD_DIR, exist_ok=True)
    files = [f for f in os.listdir(FOOD_DIR) if f.endswith(".json")]
    food_names = [f.replace(".json", "") for f in files]
    return {"available_foods": food_names}


@app.get("/foods/{food_name}")
def get_food_nutrition(food_name: str):
    """Get nutritional data for a specific food."""
    file_path = os.path.join(FOOD_DIR, f"{food_name}.json")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Food not found in database")

    with open(file_path, "r", encoding="utf-8") as file:
        food_data = json.load(file)

    return food_data


@app.post("/foods/upload")
async def upload_food_photo(
    food_name: str = Form(...),
    photo: UploadFile = File(...),
):
    """
    Upload a photo of a nutrition label. This endpoint will:
    1. Extract nutrition data from the image using Claude.
    2. Save the JSON locally to food/<food_name>.json.
    3. Push the JSON to GitHub.
    """
    if not photo.content_type or not photo.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    safe_name = re.sub(r"[^\w\-]", "", food_name)
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid food name")

    os.makedirs(FOOD_DIR, exist_ok=True)
    file_path = os.path.join(FOOD_DIR, f"{safe_name}.json")

    if os.path.exists(file_path):
        raise HTTPException(status_code=409, detail=f"'{safe_name}' already exists locally")

    image_bytes = await photo.read()
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    media_type = photo.content_type

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

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(food_data, f, ensure_ascii=False, indent=2)

    github_result = push_to_github(safe_name, food_data)

    return {
        "message": f"'{safe_name}' saved locally and pushed to GitHub",
        "data": food_data,
        "github": github_result,
    }


@app.post("/chat")
async def chat(body: dict):
    """Chat with Claude about your daily food intake using the food database as context."""
    messages = body.get("messages", [])

    # Load all food data as context
    os.makedirs(FOOD_DIR, exist_ok=True)
    foods = {}
    for f in os.listdir(FOOD_DIR):
        if f.endswith(".json"):
            name = f.replace(".json", "")
            with open(os.path.join(FOOD_DIR, f), encoding="utf-8") as fh:
                foods[name] = json.load(fh)

    system = (
        "You are a friendly nutrition assistant. "
        "The user has a food database with the following foods (name → nutrition data):\n\n"
        + json.dumps(foods, ensure_ascii=False, indent=2)
        + "\n\nWhen the user tells you what they ate, use the database to calculate totals. "
        "If a food is not in the database, estimate from common knowledge and mention it. "
        "Present totals clearly: Calories, Fat, Carbohydrates, Protein. "
        "After showing the totals, ask if they want to save this as today's intake. "
        "When the user confirms they want to save, end your message with this block (no extra text after it):\n"
        "<SAVE>\n"
        '{"items": [{"food": "<name>", "amount": "<amount>"}], '
        '"totals": {"calories": <number>, "fat_g": <number>, "carbs_g": <number>, "protein_g": <number>}}\n'
        "</SAVE>"
    )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        system=system,
        messages=messages,
    )

    raw = response.content[0].text

    # Extract save data if Claude included it
    save_data = None
    if "<SAVE>" in raw and "</SAVE>" in raw:
        start = raw.index("<SAVE>") + len("<SAVE>")
        end = raw.index("</SAVE>")
        try:
            save_data = json.loads(raw[start:end].strip())
        except json.JSONDecodeError:
            pass
        raw = raw[:raw.index("<SAVE>")].strip()

    return {"response": raw, "save_data": save_data}


@app.post("/logs")
async def save_log(body: dict):
    """Append a nutrition entry to a user's daily log file."""
    from datetime import datetime

    user = body.get("user")
    date = body.get("date")

    if user not in ALLOWED_USERS:
        raise HTTPException(status_code=400, detail=f"Invalid user. Must be one of: {ALLOWED_USERS}")
    if not date or not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise HTTPException(status_code=400, detail="Invalid or missing date (YYYY-MM-DD)")

    user_dir = os.path.join(TRACKING_DIR, user)
    os.makedirs(user_dir, exist_ok=True)
    log_path = os.path.join(user_dir, f"{date}.json")

    # Load existing log or start fresh
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as f:
            log = json.load(f)
    else:
        log = {"date": date, "user": user, "entries": [], "day_totals": {"calories": 0, "fat_g": 0, "carbs_g": 0, "protein_g": 0}}

    # Append new entry with current time
    entry = {
        "time": datetime.now().strftime("%H:%M"),
        "items": body.get("items", []),
        "totals": body.get("totals", {}),
    }
    log["entries"].append(entry)

    # Recalculate day totals
    for key in ("calories", "fat_g", "carbs_g", "protein_g"):
        log["day_totals"][key] = sum(e["totals"].get(key, 0) for e in log["entries"])

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

    return {"message": f"Entry added for {user} on {date}", "entry_count": len(log["entries"]), "day_totals": log["day_totals"]}


@app.get("/logs/{user}")
def get_user_logs(user: str):
    """List all log dates for a user."""
    if user not in ALLOWED_USERS:
        raise HTTPException(status_code=400, detail="Invalid user")

    user_dir = os.path.join(TRACKING_DIR, user)
    if not os.path.exists(user_dir):
        return {"user": user, "logs": []}

    dates = sorted([f.replace(".json", "") for f in os.listdir(user_dir) if f.endswith(".json")], reverse=True)
    return {"user": user, "logs": dates}


@app.get("/logs/{user}/{date}")
def get_user_log(user: str, date: str):
    """Get a specific day's log for a user."""
    if user not in ALLOWED_USERS:
        raise HTTPException(status_code=400, detail="Invalid user")

    log_path = os.path.join(TRACKING_DIR, user, f"{date}.json")
    if not os.path.exists(log_path):
        raise HTTPException(status_code=404, detail="Log not found")

    with open(log_path, encoding="utf-8") as f:
        return json.load(f)


@app.delete("/foods/{food_name}")
def delete_food(food_name: str):
    """
    Delete a food JSON locally and from GitHub.
    """
    safe_name = re.sub(r"[^\w\-]", "", food_name)
    file_path = os.path.join(FOOD_DIR, f"{safe_name}.json")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"'{safe_name}' not found locally")

    os.remove(file_path)

    github_result = delete_from_github(safe_name)

    return {
        "message": f"'{safe_name}' deleted locally and from GitHub",
        "github": github_result,
    }    