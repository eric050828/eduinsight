"""Tests for LTI 1.3 integration endpoints."""

from httpx import ASGITransport, AsyncClient
from litemem import Memory

from eduinsight.app import app
from eduinsight.assistant import LearningAssistant


async def _make_client(mem: Memory) -> AsyncClient:
    """Create a test client with a pre-configured in-memory assistant."""
    import eduinsight.app as app_module

    app_module._memory = mem
    app_module._assistant = LearningAssistant(mem)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


class TestJWKS:
    async def test_jwks_returns_valid_keyset(self) -> None:
        """GET /lti/jwks returns a valid JWKS with at least one key."""
        mem = Memory(":memory:")
        client = await _make_client(mem)
        resp = await client.get("/lti/jwks")
        assert resp.status_code == 200
        data = resp.json()
        assert "keys" in data
        assert len(data["keys"]) >= 1
        key = data["keys"][0]
        assert key["kty"] == "RSA"
        assert "n" in key  # modulus
        assert "e" in key  # exponent

    async def test_jwks_stable_across_calls(self) -> None:
        """JWKS returns the same key on repeated calls."""
        mem = Memory(":memory:")
        client = await _make_client(mem)
        resp1 = await client.get("/lti/jwks")
        resp2 = await client.get("/lti/jwks")
        assert resp1.json() == resp2.json()


class TestLTIConfig:
    async def test_config_returns_setup_info(self) -> None:
        """GET /lti/config returns tool setup information for Moodle admins."""
        mem = Memory(":memory:")
        client = await _make_client(mem)
        resp = await client.get("/lti/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tool_name"] == "EduInsight AI 助教"
        assert "setup_instructions" in data
        setup = data["setup_instructions"]
        assert "/lti/launch" in setup["tool_url"]
        assert "/lti/login" in setup["login_url"]
        assert "/lti/jwks" in setup["jwks_url"]


class TestLTILogin:
    async def test_login_without_config_returns_error(self) -> None:
        """POST /lti/login without LTI config returns 400 error."""
        mem = Memory(":memory:")
        client = await _make_client(mem)
        resp = await client.post(
            "/lti/login",
            data={"iss": "https://moodle.example.com", "login_hint": "42"},
        )
        # Should return error HTML since no tool config is registered
        assert resp.status_code == 400
        assert "Error" in resp.text


class TestLTILaunch:
    async def test_launch_without_token_returns_error(self) -> None:
        """POST /lti/launch without id_token returns 400 error."""
        mem = Memory(":memory:")
        client = await _make_client(mem)
        resp = await client.post("/lti/launch", data={})
        assert resp.status_code == 400
        assert "Error" in resp.text


class TestLTIHelpers:
    def test_extract_user_id_numeric(self) -> None:
        """Numeric sub claim is converted to int."""
        from eduinsight.lti import _extract_user_id
        assert _extract_user_id({"sub": "42"}) == 42

    def test_extract_user_id_non_numeric(self) -> None:
        """Non-numeric sub is hashed to a stable integer."""
        from eduinsight.lti import _extract_user_id
        result = _extract_user_id({"sub": "user-abc-123"})
        assert isinstance(result, int)
        # Same input produces same output
        assert result == _extract_user_id({"sub": "user-abc-123"})

    def test_extract_user_name_full(self) -> None:
        """Full name is extracted from 'name' claim."""
        from eduinsight.lti import _extract_user_name
        assert _extract_user_name({"name": "Alice Chen"}) == "Alice Chen"

    def test_extract_user_name_parts(self) -> None:
        """Name is composed from given_name + family_name."""
        from eduinsight.lti import _extract_user_name
        data = {"given_name": "Bob", "family_name": "Wang"}
        assert _extract_user_name(data) == "Bob Wang"

    def test_extract_course_info(self) -> None:
        """Course info is extracted from LTI context claim."""
        from eduinsight.lti import _extract_course_info
        data = {
            "https://purl.imsglobal.org/spec/lti/claim/context": {
                "id": "101",
                "label": "CS101",
                "title": "Introduction to Computer Science",
            }
        }
        info = _extract_course_info(data)
        assert info["id"] == "101"
        assert info["label"] == "CS101"
        assert info["title"] == "Introduction to Computer Science"

    def test_extract_course_info_empty(self) -> None:
        """Missing context claim returns empty strings."""
        from eduinsight.lti import _extract_course_info
        info = _extract_course_info({})
        assert info["id"] == ""
        assert info["label"] == ""


class TestLTIRoles:
    def test_extract_roles_present(self) -> None:
        """Roles are extracted from the LTI roles claim."""
        from eduinsight.lti import _extract_roles
        data = {
            "https://purl.imsglobal.org/spec/lti/claim/roles": [
                "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor",
                "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Faculty",
            ]
        }
        roles = _extract_roles(data)
        assert len(roles) == 2
        assert "Instructor" in roles[0]

    def test_extract_roles_empty(self) -> None:
        """Missing roles claim returns empty list."""
        from eduinsight.lti import _extract_roles
        assert _extract_roles({}) == []

    def test_is_instructor_true(self) -> None:
        """User with Instructor role is detected as instructor."""
        from eduinsight.lti import _is_instructor
        data = {
            "https://purl.imsglobal.org/spec/lti/claim/roles": [
                "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor",
            ]
        }
        assert _is_instructor(data) is True

    def test_is_instructor_teaching_assistant(self) -> None:
        """User with TeachingAssistant role is detected as instructor."""
        from eduinsight.lti import _is_instructor
        data = {
            "https://purl.imsglobal.org/spec/lti/claim/roles": [
                "http://purl.imsglobal.org/vocab/lis/v2/membership#TeachingAssistant",
            ]
        }
        assert _is_instructor(data) is True

    def test_is_instructor_admin(self) -> None:
        """User with Administrator role is detected as instructor."""
        from eduinsight.lti import _is_instructor
        data = {
            "https://purl.imsglobal.org/spec/lti/claim/roles": [
                "http://purl.imsglobal.org/vocab/lis/v2/system/person#Administrator",
            ]
        }
        assert _is_instructor(data) is True

    def test_is_instructor_false_for_learner(self) -> None:
        """User with only Learner role is not an instructor."""
        from eduinsight.lti import _is_instructor
        data = {
            "https://purl.imsglobal.org/spec/lti/claim/roles": [
                "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner",
            ]
        }
        assert _is_instructor(data) is False

    def test_is_instructor_false_for_empty(self) -> None:
        """No roles means not an instructor."""
        from eduinsight.lti import _is_instructor
        assert _is_instructor({}) is False

    def test_is_instructor_institution_instructor(self) -> None:
        """Institution-level Instructor role is also detected."""
        from eduinsight.lti import _is_instructor
        data = {
            "https://purl.imsglobal.org/spec/lti/claim/roles": [
                "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Instructor",
            ]
        }
        assert _is_instructor(data) is True
