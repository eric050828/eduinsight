"""Moodle Web Services REST API client.

Communicates with Moodle via its external Web Services REST API.
Requires a valid API token generated from Moodle's admin/user settings.

Reference: https://docs.moodle.org/en/Using_web_services
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class MoodleAPIError(Exception):
    """Raised when Moodle returns an error response."""

    def __init__(self, error_code: str, message: str, debug_info: str = "") -> None:
        self.error_code = error_code
        self.message = message
        self.debug_info = debug_info
        super().__init__(f"[{error_code}] {message}")


@dataclass
class MoodleCourse:
    """Simplified representation of a Moodle course."""

    id: int
    shortname: str
    fullname: str
    summary: str = ""
    category_id: int = 0


@dataclass
class MoodleAssignment:
    """Simplified representation of a Moodle assignment."""

    id: int
    course_id: int
    name: str
    intro: str = ""
    due_date: int = 0  # Unix timestamp, 0 = no due date


@dataclass
class MoodleGrade:
    """A single grade item for a user."""

    item_name: str
    grade: str  # String because Moodle can return "-" or letter grades
    grade_max: float = 100.0
    feedback: str = ""


@dataclass
class MoodleForumPost:
    """A forum discussion post."""

    id: int
    discussion_id: int
    subject: str
    message: str
    author_id: int
    author_name: str = ""
    created: int = 0  # Unix timestamp


@dataclass
class MoodleUser:
    """Basic Moodle user info."""

    id: int
    username: str
    fullname: str
    email: str = ""
    roles: list[str] = field(default_factory=list)


class MoodleClient:
    """Async client for Moodle Web Services REST API.

    Usage::

        async with MoodleClient("https://moodle.ntust.edu.tw", token="...") as client:
            courses = await client.get_user_courses()
            for c in courses:
                print(c.fullname)
    """

    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> MoodleClient:
        self._http = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            raise RuntimeError("MoodleClient must be used as async context manager")
        return self._http

    async def _call(self, function: str, **params: Any) -> Any:
        """Call a Moodle Web Service function.

        Args:
            function: The wsfunction name (e.g. "core_course_get_courses").
            **params: Additional parameters for the function.

        Returns:
            Parsed JSON response.

        Raises:
            MoodleAPIError: If Moodle returns an error.
        """
        payload = {
            "wstoken": self.token,
            "wsfunction": function,
            "moodlewsrestformat": "json",
            **params,
        }
        url = f"{self.base_url}/webservice/rest/server.php"
        logger.debug("Moodle API call: %s(%s)", function, params)

        resp = await self.http.post(url, data=payload)
        resp.raise_for_status()
        data = resp.json()

        # Moodle returns errors as {"exception": ..., "errorcode": ..., "message": ...}
        if isinstance(data, dict) and "exception" in data:
            raise MoodleAPIError(
                error_code=data.get("errorcode", "unknown"),
                message=data.get("message", "Unknown error"),
                debug_info=data.get("debuginfo", ""),
            )

        return data

    # ------------------------------------------------------------------
    # User
    # ------------------------------------------------------------------

    async def get_site_info(self) -> MoodleUser:
        """Get info about the authenticated user (token owner)."""
        data = await self._call("core_webservice_get_site_info")
        return MoodleUser(
            id=data["userid"],
            username=data["username"],
            fullname=data["fullname"],
        )

    # ------------------------------------------------------------------
    # Courses
    # ------------------------------------------------------------------

    async def get_user_courses(self, user_id: int | None = None) -> list[MoodleCourse]:
        """Get courses the user is enrolled in.

        Args:
            user_id: Moodle user ID. If None, uses the token owner's ID.
        """
        if user_id is None:
            info = await self.get_site_info()
            user_id = info.id

        data = await self._call("core_enrol_get_users_courses", userid=user_id)
        return [
            MoodleCourse(
                id=c["id"],
                shortname=c.get("shortname", ""),
                fullname=c.get("fullname", ""),
                summary=c.get("summary", ""),
                category_id=c.get("category", 0),
            )
            for c in data
        ]

    # ------------------------------------------------------------------
    # Assignments
    # ------------------------------------------------------------------

    async def get_assignments(self, course_ids: list[int]) -> list[MoodleAssignment]:
        """Get assignments for the given courses.

        Args:
            course_ids: List of Moodle course IDs.
        """
        params = {f"courseids[{i}]": cid for i, cid in enumerate(course_ids)}
        data = await self._call("mod_assign_get_assignments", **params)

        assignments: list[MoodleAssignment] = []
        for course_data in data.get("courses", []):
            cid = course_data["id"]
            for a in course_data.get("assignments", []):
                assignments.append(
                    MoodleAssignment(
                        id=a["id"],
                        course_id=cid,
                        name=a.get("name", ""),
                        intro=a.get("intro", ""),
                        due_date=a.get("duedate", 0),
                    )
                )
        return assignments

    # ------------------------------------------------------------------
    # Grades
    # ------------------------------------------------------------------

    async def get_grades(self, course_id: int, user_id: int | None = None) -> list[MoodleGrade]:
        """Get grade items for a user in a course.

        Args:
            course_id: Moodle course ID.
            user_id: Moodle user ID. If None, uses the token owner's ID.
        """
        if user_id is None:
            info = await self.get_site_info()
            user_id = info.id

        data = await self._call(
            "gradereport_user_get_grade_items",
            courseid=course_id,
            userid=user_id,
        )

        grades: list[MoodleGrade] = []
        for item in data.get("usergrades", [{}])[0].get("gradeitems", []):
            grades.append(
                MoodleGrade(
                    item_name=item.get("itemname", "") or "Course total",
                    grade=str(item.get("graderaw", "-") or "-"),
                    grade_max=float(item.get("grademax", 100)),
                    feedback=item.get("feedback", ""),
                )
            )
        return grades

    # ------------------------------------------------------------------
    # Forum posts
    # ------------------------------------------------------------------

    async def get_forum_discussions(
        self, forum_id: int, *, page: int = 0, per_page: int = 25
    ) -> list[MoodleForumPost]:
        """Get discussions from a forum.

        Args:
            forum_id: Moodle forum instance ID.
            page: Page number (0-indexed).
            per_page: Number of discussions per page.
        """
        data = await self._call(
            "mod_forum_get_forum_discussions",
            forumid=forum_id,
            page=page,
            perpage=per_page,
        )

        posts: list[MoodleForumPost] = []
        for d in data.get("discussions", []):
            posts.append(
                MoodleForumPost(
                    id=d["id"],
                    discussion_id=d["discussion"],
                    subject=d.get("subject", ""),
                    message=d.get("message", ""),
                    author_id=d.get("userid", 0),
                    author_name=d.get("userfullname", ""),
                    created=d.get("created", 0),
                )
            )
        return posts

    async def get_course_forums(self, course_id: int) -> list[dict[str, Any]]:
        """Get all forums in a course.

        Args:
            course_id: Moodle course ID.

        Returns:
            List of forum dicts with 'id', 'name', 'intro', 'type' keys.
        """
        data = await self._call("mod_forum_get_forums_by_courses", courseids=[course_id])
        return [
            {
                "id": f["id"],
                "name": f.get("name", ""),
                "intro": f.get("intro", ""),
                "type": f.get("type", "general"),
            }
            for f in data
        ]
