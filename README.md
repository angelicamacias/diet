# 🍽️ Nutrition Label Scanner

A web app that uses Claude AI to extract nutritional information from food label photos. Scan a label, save the data as JSON, and sync it automatically to GitHub.

## Features

- 📷 Upload or take a photo of a nutrition label
- 🤖 Claude AI extracts all nutritional data from the image
- 💾 Saves data as JSON locally and pushes it to GitHub
- 🔍 Search and browse your food database
- 🗑️ Delete foods from the database

## Tech stack

- **FastAPI** — Python web framework
- **Uvicorn** — ASGI server
- **Claude API (Anthropic)** — AI vision for label extraction
- **PyGithub** — syncs JSON files to a GitHub repo
- **Vanilla JS + HTML** — frontend, no frameworks

## Getting started

### 1. Clone the repo

```bash
git clone https://github.com/angelicamacias/diet.git
cd diet
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up environment variables

Create a `.env` file in the root:

```env
ANTHROPIC_API_KEY=your_anthropic_key
GITHUB_TOKEN=your_github_token
GITHUB_REPO=angelicamacias/diet
GITHUB_FOLDER=food
```

### 4. Run the app

```bash
uvicorn main:app --reload
```

Open `http://localhost:8000` in your browser.

## API endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/foods` | List all foods in the database |
| `GET` | `/foods/{name}` | Get nutritional data for a food |
| `POST` | `/foods/upload` | Upload a photo and extract nutrition data |
| `DELETE` | `/foods/{name}` | Delete a food from the database |

## Deployment

The app is deployed on Railway at [dietjson.up.railway.app](https://dietjson.up.railway.app).

Every push to `main` triggers an automatic redeploy.

### Environment variables required in Railway

- `ANTHROPIC_API_KEY`
- `GITHUB_TOKEN`
- `GITHUB_REPO`
- `GITHUB_FOLDER`
