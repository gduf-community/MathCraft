"""Single-tenant profile behavior through the registered public HTTP routes."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def profile_clients(tmp_path, monkeypatch):
    monkeypatch.setenv("MATHCRAFT_HOME", str(tmp_path))
    from MathCraft.api.main import app

    def create_client():
        # Production registrations, without unrelated model/engine startup.
        fresh_app = FastAPI()
        fresh_app.include_router(app.router)
        return TestClient(fresh_app)

    return create_client


def test_new_profile_has_teacher_identity_and_no_avatar(profile_clients):
    with profile_clients() as client:
        response = client.get("/api/user-profile")
        assert response.status_code == 200
        assert response.json() == {
            "nickname": "教师", "role": "teacher", "teaching_stage": "",
            "grade": "", "avatar_url": None,
        }
        assert client.get("/api/user-profile/avatar").status_code == 404


def test_profile_update_survives_new_http_application(profile_clients):
    details = {"nickname": "  示例教师  ", "teaching_stage": "junior", "grade": "8"}
    with profile_clients() as client:
        response = client.put("/api/user-profile", json=details)
        assert response.status_code == 200
        saved = response.json()
        assert saved == {
            "nickname": "示例教师", "role": "teacher", "teaching_stage": "junior",
            "grade": "8", "avatar_url": None,
        }
        assert client.get("/api/user-profile").json() == saved
    with profile_clients() as restarted:
        assert restarted.get("/api/user-profile").json() == saved


@pytest.mark.parametrize("extra", [{"role": "admin"}, {"role": "teacher"},
                                    {"avatar_url": "../../avatar.png"}, {"account_id": "other"}])
def test_read_only_identity_and_avatar_cannot_be_written(profile_clients, extra):
    saved = {"nickname": "原资料", "teaching_stage": "primary", "grade": "3"}
    with profile_clients() as client:
        assert client.put("/api/user-profile", json=saved).status_code == 200
        response = client.put("/api/user-profile", json={**saved, "nickname": "不应保存", **extra})
        assert response.status_code == 422
        assert client.get("/api/user-profile").json()["nickname"] == "原资料"
        assert client.get("/api/user-profile").json()["role"] == "teacher"


@pytest.mark.parametrize("changes", [
    {"nickname": ""}, {"nickname": "  "}, {"nickname": "x" * 41},
    {"nickname": "name\nline"}, {"nickname": None},
    {"teaching_stage": "university"}, {"teaching_stage": None},
    {"teaching_stage": "", "grade": "3"},
    {"teaching_stage": "primary", "grade": "7"},
    {"teaching_stage": "junior", "grade": "6"},
    {"teaching_stage": "senior", "grade": "9"},
    {"grade": "01"}, {"grade": 3}, {"grade": None},
])
def test_invalid_profile_preserves_saved_details(profile_clients, changes):
    saved = {"nickname": "原资料", "teaching_stage": "primary", "grade": "3"}
    with profile_clients() as client:
        assert client.put("/api/user-profile", json=saved).status_code == 200
        response = client.put("/api/user-profile", json={**saved, **changes})
        assert response.status_code == 422
        actual = client.get("/api/user-profile").json()
        assert {key: actual[key] for key in saved} == saved


@pytest.mark.parametrize(("stage", "grade"), [
    ("", ""), ("primary", ""), ("primary", "1"), ("primary", "6"),
    ("junior", "7"), ("junior", "9"), ("senior", "10"), ("senior", "12"),
])
def test_valid_teaching_stage_grade_combinations(profile_clients, stage, grade):
    with profile_clients() as client:
        details = {"nickname": "x" * 40, "teaching_stage": stage, "grade": grade}
        response = client.put("/api/user-profile", json=details)
        assert response.status_code == 200
        assert response.json()["teaching_stage"] == stage
        assert response.json()["grade"] == grade


def bitmap(image_format="PNG", size=(12, 8), color="red"):
    from io import BytesIO
    from PIL import Image

    output = BytesIO()
    Image.new("RGB", size, color).save(output, format=image_format)
    return output.getvalue()


def test_avatar_upload_is_independent_and_survives_new_http_application(profile_clients):
    from io import BytesIO
    from PIL import Image

    with profile_clients() as client:
        response = client.post("/api/user-profile/avatar", files={"file": ("avatar.png", bitmap(), "image/png")})
        assert response.status_code == 200
        assert response.json() == {
            "nickname": "教师", "role": "teacher", "teaching_stage": "",
            "grade": "", "avatar_url": response.json()["avatar_url"],
        }
        assert response.json()["avatar_url"].startswith("/api/user-profile/avatar?v=")
        avatar = client.get(response.json()["avatar_url"])
        assert avatar.status_code == 200
        assert avatar.headers["content-type"] == "image/png"
        with Image.open(BytesIO(avatar.content)) as image:
            assert image.size == (12, 8)
            assert image.convert("RGB").getpixel((0, 0)) == (255, 0, 0)
        saved = client.put("/api/user-profile", json={"nickname": "新昵称", "teaching_stage": "", "grade": ""})
        assert saved.status_code == 200
        assert saved.json()["avatar_url"] == response.json()["avatar_url"]
        assert client.get("/api/user-profile/avatar").content == avatar.content
    with profile_clients() as restarted:
        assert restarted.get("/api/user-profile").json() == saved.json()
        assert restarted.get("/api/user-profile/avatar").content == avatar.content


@pytest.mark.parametrize(("filename", "payload", "mime", "status"), [
    ("avatar.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>', "image/svg+xml", 400),
    ("avatar.png", b"\x89PNG\r\n\x1a\nforged", "image/png", 400),
    ("avatar.jpg", bitmap(), "image/jpeg", 400),
    ("avatar.png", bitmap("JPEG"), "image/png", 400),
    ("avatar.png", bitmap(), "application/octet-stream", 400),
    ("avatar.txt", bitmap(), "image/png", 400),
    ("../avatar.png", bitmap(), "image/png", 400),
    ("..\\avatar.png", bitmap(), "image/png", 400),
    ("avatar:stream.png", bitmap(), "image/png", 400),
    ("avatar.png", bitmap(size=(4097, 1)), "image/png", 400),
    ("avatar.png", b"x" * (5 * 1024 * 1024 + 1), "image/png", 413),
    ("avatar.png", b"", "image/png", 400),
], ids=["svg", "forged-png", "extension-mismatch", "content-mismatch", "mime-mismatch",
        "extension", "posix-path", "windows-path", "alternate-stream", "dimensions", "size", "empty"])
def test_rejected_avatar_keeps_previous_profile_and_image(profile_clients, filename, payload, mime, status):
    with profile_clients() as client:
        original = client.post("/api/user-profile/avatar", files={"file": ("old.png", bitmap(), "image/png")})
        assert original.status_code == 200
        old_avatar = client.get("/api/user-profile/avatar").content
        response = client.post("/api/user-profile/avatar", files={"file": (filename, payload, mime)})
        assert response.status_code == status
        assert client.get("/api/user-profile").json() == original.json()
        assert client.get("/api/user-profile/avatar").content == old_avatar


def test_unified_entrypoint_exposes_the_same_profile_and_avatar(profile_clients):
    from MathCraft.api.main import app

    with TestClient(app) as unified:
        assert unified.get("/api/user-profile").status_code == 200
        assert unified.get("/api/user-profile/avatar").status_code == 404
        saved = unified.put("/api/user-profile", json={"nickname": "统一入口", "teaching_stage": "senior", "grade": "12"})
        assert saved.status_code == 200
        upload = unified.post("/api/user-profile/avatar", files={"file": ("avatar.png", bitmap(), "image/png")})
        assert upload.status_code == 200
        avatar = unified.get(upload.json()["avatar_url"])
        assert avatar.status_code == 200
    with profile_clients() as knowledge:
        assert knowledge.get("/api/user-profile").json() == upload.json()
        assert knowledge.get("/api/user-profile/avatar").content == avatar.content


@pytest.mark.parametrize("resource", ["profile", "avatar"])
def test_storage_failure_preserves_previous_saved_resources(profile_clients, monkeypatch, resource):
    import os
    from pathlib import Path

    with profile_clients() as client:
        original = client.put("/api/user-profile", json={"nickname": "原资料", "teaching_stage": "primary", "grade": "3"})
        assert original.status_code == 200
        saved = client.post("/api/user-profile/avatar", files={"file": ("old.png", bitmap(), "image/png")})
        assert saved.status_code == 200
        old_avatar = client.get("/api/user-profile/avatar").content
        replace = os.replace

        def unavailable_disk(source, target):
            if Path(target).name in ("profile.json", "avatar.png"):
                raise OSError("synthetic storage failure")
            return replace(source, target)

        with monkeypatch.context() as unavailable:
            unavailable.setattr(os, "replace", unavailable_disk)
            if resource == "profile":
                response = client.put("/api/user-profile", json={"nickname": "不应保存", "teaching_stage": "", "grade": ""})
            else:
                response = client.post("/api/user-profile/avatar", files={"file": ("new.png", bitmap(color="blue"), "image/png")})
            assert response.status_code == 503
            assert "synthetic" not in response.text
        assert client.get("/api/user-profile").json() == saved.json()
        assert client.get("/api/user-profile/avatar").content == old_avatar
    with profile_clients() as restarted:
        assert restarted.get("/api/user-profile").json() == saved.json()
        assert restarted.get("/api/user-profile/avatar").content == old_avatar


@pytest.mark.parametrize(("image_format", "filename", "mime"), [
    ("PNG", "avatar.PNG", "image/png"),
    ("JPEG", "avatar.jpeg", "image/jpeg"),
    ("WEBP", "avatar.webp", "image/webp"),
])
def test_supported_bitmap_formats_replace_avatar_as_safe_png(profile_clients, image_format, filename, mime):
    from io import BytesIO
    from PIL import Image

    with profile_clients() as client:
        assert client.post("/api/user-profile/avatar", files={"file": ("old.png", bitmap(), "image/png")}).status_code == 200
        old = client.get("/api/user-profile/avatar").content
        response = client.post("/api/user-profile/avatar", files={"file": (filename, bitmap(image_format, color="blue"), mime)})
        assert response.status_code == 200
        assert response.json()["avatar_url"].startswith("/api/user-profile/avatar?v=")
        avatar = client.get(response.json()["avatar_url"])
        assert avatar.content != old
        assert avatar.headers["cache-control"] == "no-store"
        assert avatar.headers["x-content-type-options"] == "nosniff"
        with Image.open(BytesIO(avatar.content)) as image:
            assert image.format == "PNG"
            assert image.size == (12, 8)
            assert image.convert("RGB").getpixel((0, 0))[2] >= 250


def test_avatar_metadata_and_trailing_payload_are_not_served(profile_clients):
    from io import BytesIO
    from PIL import Image, PngImagePlugin

    source = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("private-note", "synthetic-private-metadata")
    Image.new("RGB", (2, 2)).save(source, format="PNG", pnginfo=metadata)
    payload = source.getvalue() + b"<script>synthetic-executable-marker</script>"
    with profile_clients() as client:
        response = client.post("/api/user-profile/avatar", files={"file": ("avatar.png", payload, "image/png")})
        assert response.status_code == 200
        assert response.json()["avatar_url"].startswith("/api/user-profile/avatar?v=")
        avatar = client.get(response.json()["avatar_url"])
        assert b"synthetic-private-metadata" not in avatar.content
        assert b"synthetic-executable-marker" not in avatar.content
        with Image.open(BytesIO(avatar.content)) as image:
            assert "private-note" not in image.info


def test_animated_avatar_is_rejected_without_replacing_saved_image(profile_clients):
    from io import BytesIO
    from PIL import Image

    animation = BytesIO()
    Image.new("RGB", (2, 2), "red").save(
        animation, format="WEBP", save_all=True,
        append_images=[Image.new("RGB", (2, 2), "blue")], duration=100, loop=0,
    )
    with profile_clients() as client:
        assert client.post("/api/user-profile/avatar", files={"file": ("old.png", bitmap(), "image/png")}).status_code == 200
        old = client.get("/api/user-profile/avatar").content
        response = client.post("/api/user-profile/avatar", files={"file": ("animated.webp", animation.getvalue(), "image/webp")})
        assert response.status_code == 400
        assert client.get("/api/user-profile/avatar").content == old


def test_runtime_roots_do_not_share_personal_information(profile_clients, tmp_path, monkeypatch):
    original_home = str(tmp_path)
    with profile_clients() as client:
        assert client.put("/api/user-profile", json={"nickname": "原资料", "teaching_stage": "", "grade": ""}).status_code == 200
        saved = client.post("/api/user-profile/avatar", files={"file": ("old.png", bitmap(), "image/png")})
        assert saved.status_code == 200
        old = client.get("/api/user-profile/avatar").content
    monkeypatch.setenv("MATHCRAFT_HOME", str(tmp_path / "another-runtime"))
    with profile_clients() as other:
        assert other.get("/api/user-profile").json() == {
            "nickname": "教师", "role": "teacher", "teaching_stage": "",
            "grade": "", "avatar_url": None,
        }
        assert other.get("/api/user-profile/avatar").status_code == 404
    monkeypatch.setenv("MATHCRAFT_HOME", original_home)
    with profile_clients() as original:
        assert original.get("/api/user-profile").json() == saved.json()
        assert original.get("/api/user-profile/avatar").content == old


def test_missing_avatar_file_does_not_create_resource(profile_clients):
    with profile_clients() as client:
        assert client.post("/api/user-profile/avatar").status_code == 422
        assert client.get("/api/user-profile").json()["avatar_url"] is None
        assert client.get("/api/user-profile/avatar").status_code == 404


def test_replaced_avatar_gets_new_stable_resource_url(profile_clients):
    from urllib.parse import urlsplit

    with profile_clients() as client:
        first = client.post("/api/user-profile/avatar", files={"file": ("first.png", bitmap(), "image/png")})
        assert first.status_code == 200
        first_url = first.json()["avatar_url"]
        assert urlsplit(first_url).path == "/api/user-profile/avatar"
        assert urlsplit(first_url).query
        assert client.get(first_url).status_code == 200
        second = client.post("/api/user-profile/avatar", files={"file": ("next.png", bitmap(color="blue"), "image/png")})
        assert second.status_code == 200
        second_url = second.json()["avatar_url"]
        assert second_url != first_url
        assert client.get(second_url).status_code == 200
        assert client.get("/api/user-profile").json()["avatar_url"] == second_url
    with profile_clients() as restarted:
        assert restarted.get("/api/user-profile").json()["avatar_url"] == second_url
        assert restarted.get(second_url).status_code == 200
