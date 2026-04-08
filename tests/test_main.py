import json
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def temp_food_dir(tmp_path):
    """Redirect FOOD_DIR to a temp directory for every test."""
    original = main.FOOD_DIR
    main.FOOD_DIR = str(tmp_path)
    yield tmp_path
    main.FOOD_DIR = original


# ---------------------------------------------------------------------------
# GET /foods
# ---------------------------------------------------------------------------

def test_list_foods_empty(temp_food_dir):
    res = client.get("/foods")
    assert res.status_code == 200
    assert res.json() == {"available_foods": []}


def test_list_foods_returns_names(temp_food_dir):
    (temp_food_dir / "apple.json").write_text("{}")
    (temp_food_dir / "banana.json").write_text("{}")

    res = client.get("/foods")
    assert res.status_code == 200
    assert sorted(res.json()["available_foods"]) == ["apple", "banana"]


# ---------------------------------------------------------------------------
# GET /foods/{food_name}
# ---------------------------------------------------------------------------

def test_get_food_found(temp_food_dir):
    data = {"calorias_porcion": "100", "nutrientes": []}
    (temp_food_dir / "yogurt.json").write_text(json.dumps(data))

    res = client.get("/foods/yogurt")
    assert res.status_code == 200
    assert res.json() == data


def test_get_food_not_found(temp_food_dir):
    res = client.get("/foods/ghost")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /foods/{food_name}
# ---------------------------------------------------------------------------

def test_delete_food(temp_food_dir):
    (temp_food_dir / "chips.json").write_text("{}")

    with patch("main.delete_from_github", return_value={"action": "deleted"}):
        res = client.delete("/foods/chips")

    assert res.status_code == 200
    assert not (temp_food_dir / "chips.json").exists()


def test_delete_food_not_found(temp_food_dir):
    with patch("main.delete_from_github", return_value={"action": "skipped"}):
        res = client.delete("/foods/ghost")

    assert res.status_code == 404


# ---------------------------------------------------------------------------
# POST /foods/upload
# ---------------------------------------------------------------------------

FAKE_NUTRITION = {
    "tamaño_porcion": "30g",
    "calorias_porcion": "120",
    "nutrientes": [
        {
            "nutriente": "Grasa",
            "cantidad_porcion": "5g",
            "cantidad_100g_ml": "16.7g",
            "porcentaje_vd": "6%",
        }
    ],
}


def _make_claude_response(text: str):
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


def test_upload_food_success(temp_food_dir):
    with (
        patch("main.anthropic.Anthropic") as MockClient,
        patch("main.push_to_github", return_value={"action": "created"}),
    ):
        MockClient.return_value.messages.create.return_value = _make_claude_response(
            json.dumps(FAKE_NUTRITION)
        )

        image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # minimal fake PNG
        res = client.post(
            "/foods/upload",
            data={"food_name": "testfood"},
            files={"photo": ("label.png", image, "image/png")},
        )

    assert res.status_code == 200
    assert res.json()["data"] == FAKE_NUTRITION
    assert (temp_food_dir / "testfood.json").exists()


def test_upload_food_already_exists(temp_food_dir):
    (temp_food_dir / "testfood.json").write_text("{}")

    image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    res = client.post(
        "/foods/upload",
        data={"food_name": "testfood"},
        files={"photo": ("label.png", image, "image/png")},
    )

    assert res.status_code == 409


def test_upload_food_invalid_name(temp_food_dir):
    image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    res = client.post(
        "/foods/upload",
        data={"food_name": "!!!"},
        files={"photo": ("label.png", image, "image/png")},
    )

    assert res.status_code == 400


def test_upload_food_not_an_image(temp_food_dir):
    res = client.post(
        "/foods/upload",
        data={"food_name": "testfood"},
        files={"photo": ("doc.pdf", b"%PDF", "application/pdf")},
    )

    assert res.status_code == 400


def test_upload_food_bad_claude_response(temp_food_dir):
    with (
        patch("main.anthropic.Anthropic") as MockClient,
        patch("main.push_to_github", return_value={"action": "created"}),
    ):
        MockClient.return_value.messages.create.return_value = _make_claude_response(
            "This is not JSON at all"
        )

        image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        res = client.post(
            "/foods/upload",
            data={"food_name": "badfood"},
            files={"photo": ("label.png", image, "image/png")},
        )

    assert res.status_code == 502
