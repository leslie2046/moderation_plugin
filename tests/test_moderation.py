import itertools
import json
from pathlib import Path

import pytest
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request
from dify_plugin.entities.endpoint import EndpointProviderConfiguration
from dify_plugin.core.entities.plugin.setup import PluginConfiguration
from dify_plugin.core.utils.yaml_loader import load_yaml_file

from endpoints.moderation import ModerationEndpoint


@pytest.fixture
def settings():
    return {"api_key": "test-key", "keywords": "敏感 bad", "separator": " ",
            "input_preset_response": "输入被拦截", "output_preset_response": "输出被拦截"}


def invoke(settings, body=None, auth="Bearer test-key", raw=None, content_type="application/json"):
    builder = EnvironBuilder(method="POST", data=json.dumps(body) if raw is None else raw,
                             content_type=content_type,
                             headers={} if auth is None else {"Authorization": auth})
    request = Request(builder.get_environ())
    # The endpoint logic requires no SDK session; use the actual SDK class.
    endpoint = object.__new__(ModerationEndpoint)
    return endpoint._invoke(request, {}, settings)


@pytest.mark.parametrize("stage,params", [("input", {"query": "敏感内容"}),
                                         ("input", {"inputs": {"name": "bad"}}),
                                         ("output", {"text": "bad result"})])
def test_default_block(settings, stage, params):
    response = invoke(settings, {"point": f"app.moderation.{stage}", "params": params})
    assert response.status_code == 200
    assert response.json == {"flagged": True, "action": "direct_output",
                             "preset_response": settings[f"{stage}_preset_response"]}


@pytest.mark.parametrize("stage", ["input", "output"])
def test_no_match_and_missing_fields(settings, stage):
    response = invoke(settings, {"point": f"app.moderation.{stage}"})
    assert response.json == {"flagged": False, "action": "direct_output"}


def test_input_mask_preserves_non_strings(settings):
    settings["input_strategy"] = "overridden"
    inputs = {"name": "bad敏感", "count": 3, "enabled": True, "empty": None,
              "file": {"name": "bad.txt"}, "list": ["bad"]}
    response = invoke(settings, {"point": "app.moderation.input",
                                 "params": {"inputs": inputs, "query": "bad query"}})
    assert response.json == {"flagged": True, "action": "overridden",
                             "inputs": {**inputs, "name": "******"}, "query": "*** query"}


def test_non_string_values_without_match(settings):
    response = invoke(settings, {"point": "app.moderation.input",
                                 "params": {"inputs": {"count": 1, "flag": False, "file": {"name": "bad"}}}})
    assert response.status_code == 200
    assert response.json["flagged"] is False


def test_output_mask(settings):
    settings["output_strategy"] = "overridden"
    response = invoke(settings, {"point": "app.moderation.output", "params": {"text": "bad敏感 good"}})
    assert response.json == {"flagged": True, "action": "overridden", "text": "****** good"}


@pytest.mark.parametrize("keywords", list(itertools.permutations(["abc", "bcde", "ab"])))
def test_overlapping_keyword_order(keywords):
    assert ModerationEndpoint._mask_words("xabcdef", list(keywords)) == "x***f"


@pytest.mark.parametrize("text,keywords,expected", [
    ("ababa", ["aba"], "***"), ("aaaa", ["aa"], "***"),
    ("a+b (x)", ["a+b", "(x)"], "*** ***"),
    ("badbad", ["bad"], "******"), ("***bad", ["bad", "*"], "************"),
    ("safe", ["bad"], "safe"), ("敏感内容", ["敏感", "敏感内容"], "***"),
])
def test_mask_regressions(text, keywords, expected):
    assert ModerationEndpoint._mask_words(text, keywords) == expected


@pytest.mark.parametrize("auth,status", [(None, 401), ("Basic test-key", 401),
                                         ("Bearer ", 401), ("Bearer wrong", 403),
                                         ("Bearer 非法", 403)])
def test_auth_before_body_parsing(settings, auth, status):
    response = invoke(settings, auth=auth, raw="not json")
    assert response.status_code == status
    assert response.mimetype == "application/json"


@pytest.mark.parametrize("key", ["", " ", None, 4])
def test_empty_or_invalid_configured_key(settings, key):
    settings["api_key"] = key
    assert invoke(settings, {"point": "ping"}).status_code == 500


def test_ping_needs_only_api_key():
    response = invoke({"api_key": "test-key"}, {"point": "ping"}, auth="bearer test-key")
    assert response.status_code == 200
    assert response.json == {"result": "pong"}


@pytest.mark.parametrize("raw,content_type", [("{", "application/json"),
                                             ("{}", "text/plain"), ("", "application/json")])
def test_invalid_json(settings, raw, content_type):
    assert invoke(settings, raw=raw, content_type=content_type).status_code == 400


@pytest.mark.parametrize("body", [None, [], "text", 3, {}, {"point": "unknown"},
    {"point": "app.moderation.input", "params": None},
    {"point": "app.moderation.input", "params": {"inputs": []}},
    {"point": "app.moderation.input", "params": {"query": None}},
    {"point": "app.moderation.output", "params": {"text": 4}},
    {"point": "app.moderation.output", "params": []},
])
def test_invalid_payload(settings, body):
    response = invoke(settings, body)
    assert response.status_code == 400
    assert "error" in response.json
    assert "flagged" not in response.json


@pytest.mark.parametrize("setting,value", [("separator", ""), ("separator", None),
    ("keywords", "  "), ("keywords", None), ("input_strategy", "unknown"),
    ("input_preset_response", 12)])
def test_invalid_settings(settings, setting, value):
    settings[setting] = value
    assert invoke(settings, {"point": "app.moderation.input"}).status_code == 500


def test_invalid_output_strategy(settings):
    settings["output_strategy"] = "unknown"
    assert invoke(settings, {"point": "app.moderation.output"}).status_code == 500


def test_custom_separator_duplicate_and_empty_entries(settings):
    settings.update(keywords=" bad || ||敏感||bad|| ", separator="||", output_strategy="overridden")
    response = invoke(settings, {"point": "app.moderation.output", "params": {"text": "bad敏感"}})
    assert response.json["text"] == "******"


def test_literal_case_sensitive_matching(settings):
    response = invoke(settings, {"point": "app.moderation.output", "params": {"text": "BAD"}})
    assert response.json["flagged"] is False


def test_sdk_declarations():
    declaration = PluginConfiguration.model_validate(load_yaml_file("manifest.yaml"))
    assert str(declaration.version) == "0.0.3"
    group = EndpointProviderConfiguration.model_validate(load_yaml_file("group/moderation.yaml"))
    strategies = {item.name: item for item in group.settings if item.name.endswith("_strategy")}
    assert set(strategies) == {"input_strategy", "output_strategy"}
    assert all(item.default == "direct_output" for item in strategies.values())
    assert Path("_assets/icon.png").is_file()
