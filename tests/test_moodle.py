"""Tests for the Moodle API client.

Uses httpx mock to avoid real network calls.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from eduinsight.moodle import MoodleAPIError, MoodleClient


@pytest.fixture
def mock_response():
    """Helper to create mock httpx responses."""
    def _make(json_data, status_code=200):
        resp = httpx.Response(
            status_code=status_code,
            json=json_data,
            request=httpx.Request("POST", "https://moodle.test/webservice/rest/server.php"),
        )
        return resp
    return _make


class TestMoodleClient:
    @pytest.mark.asyncio
    async def test_get_site_info(self, mock_response) -> None:
        client = MoodleClient("https://moodle.test", token="testtoken")
        async with client:
            with patch.object(client.http, "post", new_callable=AsyncMock) as mock_post:
                mock_post.return_value = mock_response({
                    "userid": 42,
                    "username": "student1",
                    "fullname": "Test Student",
                })
                info = await client.get_site_info()
                assert info.id == 42
                assert info.username == "student1"
                assert info.fullname == "Test Student"

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mock_response) -> None:
        client = MoodleClient("https://moodle.test", token="badtoken")
        async with client:
            with patch.object(client.http, "post", new_callable=AsyncMock) as mock_post:
                mock_post.return_value = mock_response({
                    "exception": "webservice_access_exception",
                    "errorcode": "accessexception",
                    "message": "Access denied",
                })
                with pytest.raises(MoodleAPIError, match="Access denied"):
                    await client.get_site_info()

    @pytest.mark.asyncio
    async def test_get_user_courses(self, mock_response) -> None:
        client = MoodleClient("https://moodle.test", token="testtoken")
        async with client:
            with patch.object(client.http, "post", new_callable=AsyncMock) as mock_post:
                # First call: get_site_info for user_id
                # Second call: get_users_courses
                mock_post.side_effect = [
                    mock_response({
                        "userid": 42,
                        "username": "student1",
                        "fullname": "Test Student",
                    }),
                    mock_response([
                        {
                            "id": 101,
                            "shortname": "CS101",
                            "fullname": "Intro to CS",
                            "summary": "Learn CS basics",
                            "category": 5,
                        },
                        {
                            "id": 102,
                            "shortname": "MATH201",
                            "fullname": "Linear Algebra",
                            "summary": "",
                            "category": 3,
                        },
                    ]),
                ]
                courses = await client.get_user_courses()
                assert len(courses) == 2
                assert courses[0].shortname == "CS101"
                assert courses[1].fullname == "Linear Algebra"

    @pytest.mark.asyncio
    async def test_context_manager_required(self) -> None:
        client = MoodleClient("https://moodle.test", token="testtoken")
        with pytest.raises(RuntimeError, match="context manager"):
            _ = client.http

    @pytest.mark.asyncio
    async def test_get_assignments(self, mock_response) -> None:
        client = MoodleClient("https://moodle.test", token="testtoken")
        async with client:
            with patch.object(client.http, "post", new_callable=AsyncMock) as mock_post:
                mock_post.return_value = mock_response({
                    "courses": [
                        {
                            "id": 101,
                            "assignments": [
                                {
                                    "id": 1,
                                    "name": "HW1",
                                    "intro": "First homework",
                                    "duedate": 1700000000,
                                }
                            ],
                        }
                    ]
                })
                assignments = await client.get_assignments([101])
                assert len(assignments) == 1
                assert assignments[0].name == "HW1"
                assert assignments[0].course_id == 101
