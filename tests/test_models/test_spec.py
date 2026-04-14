"""Unit tests for spec data models."""

from specs_agent.models.spec import (
    Endpoint,
    HttpMethod,
    Parameter,
    ParameterLocation,
    ParsedSpec,
    ResponseSpec,
    ServerInfo,
)


class TestHttpMethod:
    def test_all_methods_exist(self):
        methods = [m.value for m in HttpMethod]
        assert "GET" in methods
        assert "POST" in methods
        assert "PUT" in methods
        assert "PATCH" in methods
        assert "DELETE" in methods
        assert "OPTIONS" in methods
        assert "HEAD" in methods

    def test_string_comparison(self):
        assert HttpMethod.GET == "GET"
        assert HttpMethod.POST == "POST"

    def test_from_string(self):
        assert HttpMethod("GET") is HttpMethod.GET
        assert HttpMethod("DELETE") is HttpMethod.DELETE


class TestParameterLocation:
    def test_all_locations(self):
        locs = [loc.value for loc in ParameterLocation]
        assert set(locs) == {"query", "path", "header", "cookie", "body"}


class TestParameter:
    def test_defaults(self):
        p = Parameter(name="id", location=ParameterLocation.PATH, required=True)
        assert p.schema_type == "string"
        assert p.description == ""
        assert p.default is None
        assert p.example is None
        assert p.enum_values == []

    def test_with_enum(self):
        p = Parameter(
            name="status",
            location=ParameterLocation.QUERY,
            required=False,
            enum_values=["active", "inactive"],
        )
        assert len(p.enum_values) == 2


class TestResponseSpec:
    def test_basic(self):
        r = ResponseSpec(status_code=200, description="OK")
        assert r.status_code == 200
        assert r.schema is None

    def test_with_schema(self):
        schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
        r = ResponseSpec(status_code=200, description="OK", schema=schema)
        assert r.schema is not None
        assert r.schema["type"] == "object"


class TestEndpoint:
    def test_display_name_with_operation_id(self):
        ep = Endpoint(
            path="/pets",
            method=HttpMethod.GET,
            operation_id="listPets",
        )
        assert ep.display_name == "listPets"

    def test_display_name_without_operation_id(self):
        ep = Endpoint(path="/pets", method=HttpMethod.GET)
        assert ep.display_name == "GET /pets"

    def test_defaults(self):
        ep = Endpoint(path="/test", method=HttpMethod.POST)
        assert ep.summary == ""
        assert ep.description == ""
        assert ep.tags == []
        assert ep.parameters == []
        assert ep.request_body_schema is None
        assert ep.responses == []
        assert ep.security == []


class TestServerInfo:
    def test_basic(self):
        s = ServerInfo(url="https://api.example.com")
        assert s.url == "https://api.example.com"
        assert s.description == ""


class TestParsedSpec:
    def test_base_url_from_servers(self):
        spec = ParsedSpec(
            title="Test",
            version="1.0",
            servers=[ServerInfo(url="https://api.example.com/v1/")],
        )
        assert spec.base_url == "https://api.example.com/v1"

    def test_base_url_strips_trailing_slash(self):
        spec = ParsedSpec(
            title="Test",
            version="1.0",
            servers=[ServerInfo(url="https://api.example.com/")],
        )
        assert spec.base_url == "https://api.example.com"

    def test_base_url_no_servers(self):
        spec = ParsedSpec(title="Test", version="1.0")
        assert spec.base_url == "http://localhost"

    def test_endpoints_by_tag_grouping(self):
        ep1 = Endpoint(path="/a", method=HttpMethod.GET, tags=["alpha"])
        ep2 = Endpoint(path="/b", method=HttpMethod.POST, tags=["alpha"])
        ep3 = Endpoint(path="/c", method=HttpMethod.GET, tags=["beta"])
        spec = ParsedSpec(
            title="Test",
            version="1.0",
            endpoints=[ep1, ep2, ep3],
        )
        by_tag = spec.endpoints_by_tag
        assert len(by_tag["alpha"]) == 2
        assert len(by_tag["beta"]) == 1

    def test_endpoints_by_tag_default(self):
        ep = Endpoint(path="/x", method=HttpMethod.GET, tags=[])
        spec = ParsedSpec(title="Test", version="1.0", endpoints=[ep])
        by_tag = spec.endpoints_by_tag
        assert "default" in by_tag
        assert len(by_tag["default"]) == 1

    def test_endpoints_by_tag_multi_tag(self):
        ep = Endpoint(path="/x", method=HttpMethod.GET, tags=["a", "b"])
        spec = ParsedSpec(title="Test", version="1.0", endpoints=[ep])
        by_tag = spec.endpoints_by_tag
        assert ep in by_tag["a"]
        assert ep in by_tag["b"]

    def test_empty_spec(self):
        spec = ParsedSpec(title="Empty", version="0.0")
        assert spec.endpoints == []
        assert spec.tags == []
        assert spec.endpoints_by_tag == {}
