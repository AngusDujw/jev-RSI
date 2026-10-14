"""Task-scoped GPT-6.1 Sol high Responses transport for the method-only planner."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
import tomllib
import urllib.error
import urllib.request


DEFAULT_CODEX_HOME = Path(
    "/home/v4090-1/DataStorage/gpt6-dec/secrets/ai2robcowork-codex")


def load_config() -> dict:
    directory = Path(os.environ.get("ROBODOJO_PLANNER_CODEX_HOME",
                                    str(DEFAULT_CODEX_HOME)))
    config = tomllib.loads((directory / "config.toml").read_text())
    auth = json.loads((directory / "auth.json").read_text())
    provider_name = config.get("model_provider")
    provider = config.get("model_providers", {}).get(provider_name, {})
    if (provider_name != "ai2robcowork" or
            config.get("model") != "gpt-6.1-sol" or
            config.get("preferred_auth_method") != "apikey" or
            provider.get("wire_api") != "responses" or
            provider.get("requires_openai_auth") is not True):
        raise ValueError("Planner Codex configuration violates the requested provider contract")
    base = provider.get("base_url")
    if base != "https://ai2robcowork.site/openai/v1":
        raise ValueError("Planner provider URL differs from the authorized endpoint")
    key = auth.get("OPENAI_API_KEY")
    if not isinstance(key, str) or not key:
        raise ValueError("Task-scoped planner API key is unavailable")
    return {"model": config["model"], "base_url": base, "api_key": key,
            "config_dir": str(directory)}


def build_payload(system: str, legacy_parts: list[dict], model: str) -> dict:
    content = []
    for part in legacy_parts:
        if part["type"] == "text":
            content.append({"type": "input_text", "text": part["text"]})
        elif part["type"] == "image_url":
            content.append({"type": "input_image",
                            "image_url": part["image_url"]["url"],
                            "detail": "high"})
        else:
            raise ValueError("Planner input has an unsupported content type")
    return {
        "model": model,
        "reasoning": {"effort": "high"},
        "text": {"format": {"type": "json_object"}},
        "store": False,
        "stream": False,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
    }


class PlannerRetryable(RuntimeError):
    """Provider reported temporary capacity failure or an incomplete stream."""


def output_text(response: dict) -> str:
    wrapped = response.get("output_text")
    if isinstance(wrapped, str) and wrapped.startswith("event: "):
        events = []
        for frame in wrapped.split("\n\n"):
            data = [line[6:] for line in frame.splitlines()
                    if line.startswith("data: ")]
            if data:
                events.append(json.loads("\n".join(data)))
        for event in events:
            if event.get('type')=='response.incomplete':
                incomplete=event.get('response',{})
                reason=(incomplete.get('incomplete_details') or {}).get('reason','unknown')
                usage=incomplete.get('usage') or {}
                raise ValueError('Planner incomplete: '+reason+'; output_tokens='+
                                 str(usage.get('output_tokens'))+'; no completed method')
            if event.get("type") in ("error", "response.failed"):
                detail = event.get("error") or event.get("response", {}).get("error") or {}
                code = detail.get("code", "unknown")
                if code in ("server_is_overloaded", "rate_limit_exceeded", "service_unavailable", "server_error"):
                    raise PlannerRetryable("Planner provider temporary failure: " + code)
                raise ValueError("Planner provider response failed: " + code)
        completed = [event["response"] for event in events
                     if event.get("type") == "response.completed"]
        if completed:
            return output_text(completed[-1])
        raise PlannerRetryable("Planner provider stream ended without completion")
    if response.get("status") not in (None, "completed"):
        raise ValueError("Planner Responses call is not complete")
    if isinstance(wrapped, str) and wrapped:
        return wrapped
    pieces = []
    for item in response.get("output", []):
        if item.get("type") != "message" or item.get("role") != "assistant":
            continue
        for block in item.get("content", []):
            if block.get("type") == "output_text" and isinstance(block.get("text"), str):
                pieces.append(block["text"])
            elif block.get("type") == "refusal":
                raise ValueError("Planner model refused the method-only request")
    if not pieces:
        raise ValueError("Planner Responses output contains no assistant text")
    return "".join(pieces)


def request(payload: dict, configuration: dict) -> dict:
    url = configuration["base_url"].rstrip("/") + "/responses"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = {
        "Authorization": "Bearer " + configuration["api_key"],
        "Content-Type": "application/json",
    }
    last_error = None
    long_request = os.environ.get('ROBODOJO_PLANNER_LONG_REQUEST') == '1'
    attempts, timeout = (1, 210) if long_request else (2, 95)
    explicit_timeout = os.environ.get('ROBODOJO_PLANNER_REQUEST_TIMEOUT_SECONDS')
    if explicit_timeout is not None:
        timeout = int(explicit_timeout)
        if not 30 <= timeout <= 1800:
            raise ValueError('Planner explicit timeout must be within30..1800 seconds')
        attempts = 1
    for attempt in range(attempts):
        call = urllib.request.Request(url, data=body, headers=header, method="POST")
        try:
            if os.environ.get('ROBODOJO_PLANNER_TRANSPORT')=='ssh_stdio':
                from decision_stdio import request as stdio_request
                response=stdio_request(payload,timeout,service='planner')
            else:
                with urllib.request.urlopen(call, timeout=timeout) as handle:
                    response = json.load(handle)
            output_text(response)
            return response
        except PlannerRetryable as error:
            last_error = str(error)
        except urllib.error.HTTPError as error:
            if error.code not in (408, 429, 500, 502, 503, 504):
                raise RuntimeError(
                    f"Planner Responses HTTP {error.code} from requested provider") from error
            last_error = f"HTTP {error.code}"
        except urllib.error.URLError as error:
            # Diagnose transport vs provider latency without logging headers,
            # credentials or potentially sensitive exception text.
            last_error = ('URLError reason_type=' + type(error.reason).__name__ +
                          ' errno=' + str(getattr(error.reason, 'errno', None)))
        except (TimeoutError, json.JSONDecodeError) as error:
            last_error = type(error).__name__
        if attempt + 1 < attempts:
            time.sleep(20)
    raise RuntimeError("Planner Responses failed after bounded retries: " + str(last_error))
