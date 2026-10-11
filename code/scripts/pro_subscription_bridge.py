"""Loopback-only Chat Completions bridge to the signed-in local Codex CLI.

The bridge never reads API keys. A remote RoboDojo worker can reach it only
through an explicit SSH reverse tunnel, and each request is an ephemeral Codex
turn using the user's ChatGPT subscription authentication.
"""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid


PROJECT = Path(__file__).resolve().parents[1]
MODEL = 'gpt-6.1-sol'
EFFORT = 'high'
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"response_text": {"type": "string"}},
    "required": ["response_text"],
}


class InvalidRequest(ValueError):
    """The caller sent a request this bridge cannot execute."""


def complete(body, root, codex):
    if not isinstance(body, dict):
        raise InvalidRequest("A JSON object request is required")
    if body.get("model") != MODEL or body.get("reasoning_effort") != EFFORT:
        raise InvalidRequest("This bridge accepts only gpt-6.1-sol with high reasoning")
    if body.get("response_format") != {"type": "json_object"} or body.get("stream", False):
        raise InvalidRequest("This bridge accepts non-streaming JSON-object requests")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise InvalidRequest("A nonempty messages list is required")

    folder = root / uuid.uuid4().hex
    folder.mkdir(parents=True)
    (folder / "response.schema.json").write_text(json.dumps(SCHEMA))
    prompt_messages = []
    images = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in {"system", "developer", "user", "assistant"}:
            raise InvalidRequest("Unsupported message")
        content = message.get("content")
        if isinstance(content, str):
            prompt_messages.append({"role": message["role"], "content": content})
            continue
        if not isinstance(content, list):
            raise InvalidRequest("Unsupported message content")
        parts = []
        for part in content:
            if not isinstance(part, dict):
                raise InvalidRequest("Unsupported content part")
            if part.get("type") == "text":
                parts.append(part.get("text", ""))
            elif part.get("type") == "image_url":
                image_part = part.get("image_url")
                if not isinstance(image_part, dict):
                    raise InvalidRequest("Invalid image_url content part")
                url = image_part.get("url", "")
                mime = next((m for m in ("image/jpeg", "image/png", "image/webp")
                             if url.startswith("data:" + m + ";base64,")), None)
                if mime is None:
                    raise InvalidRequest("Only inline JPEG, PNG and WebP images are supported")
                suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[mime]
                image = folder / f"image_{len(images):03d}{suffix}"
                image.write_bytes(base64.b64decode(url.split(",", 1)[1], validate=True))
                images.append(image)
                parts.append(f"[Attached image {len(images)}: {image.name}]")
            else:
                raise InvalidRequest("Unsupported content part")
        prompt_messages.append({"role": message["role"], "content": parts})

    prompt = (
        "You are the model component of a robotics planning request. Produce the assistant "
        "response to the supplied conversation. Obey its system instructions and inspect "
        "the attached images directly. Do not use tools, run commands, browse, or inspect "
        "other files. The caller validates and executes the result. Return only the required "
        "response envelope; its response_text must contain the requested JSON object, "
        "without Markdown fences. Image markers identify attachment order.\n\n"
        + json.dumps(prompt_messages, ensure_ascii=False)
    )
    output = folder / "response.json"
    command = [codex, "exec", "--ignore-user-config", "--ephemeral",
               "--skip-git-repo-check", "--sandbox", "read-only", "-C", str(folder),
               "--model", MODEL, "-c", f'model_reasoning_effort="{EFFORT}"',
               "--json", "--output-schema", str(folder / "response.schema.json"),
               "--output-last-message", str(output)]
    for image in images:
        command.extend(["--image", str(image)])
    command.append("-")
    environment = dict(os.environ)
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_HOME"):
        environment.pop(name, None)
    scratch = root / "scratch"
    scratch.mkdir(exist_ok=True)
    environment["TMPDIR"] = str(scratch)
    started = time.time()
    with (folder / "events.jsonl").open("w") as events, (folder / "stderr.log").open("w") as errors:
        result = subprocess.run(command, input=prompt, text=True, env=environment,
                                stdout=events, stderr=errors, timeout=1200, check=False)
    if result.returncode or not output.exists():
        raise RuntimeError("Local Codex subscription turn failed; see bridge job logs")
    envelope = json.loads(output.read_text())
    response_text = envelope["response_text"]
    if not isinstance(json.loads(response_text), dict):
        raise ValueError("Planner response must be a JSON object")
    usage = None
    for line in (folder / "events.jsonl").read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed" and event.get("usage"):
            u = event["usage"]
            usage = {
                "input_tokens": u["input_tokens"], "output_tokens": u["output_tokens"],
                "total_tokens": u["input_tokens"] + u["output_tokens"],
                "input_tokens_details": {"cached_tokens": u.get("cached_input_tokens", 0),
                                         "cache_write_tokens": u.get("cache_write_input_tokens", 0)},
                "output_tokens_details": {"reasoning_tokens": u.get("reasoning_output_tokens", 0)},
            }
    answer = {
        "id": "chatcmpl-" + folder.name, "object": "chat.completion",
        "created": int(started), "model": MODEL,
        "model_provenance": "requested_codex_cli_model_via_chatgpt_subscription",
        "usage": usage,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": response_text},
                     "finish_reason": "stop"}],
    }
    (folder / "completion.json").write_text(json.dumps(answer, ensure_ascii=False, indent=2))
    print(f"completed job={folder.name} images={len(images)} seconds={time.time()-started:.1f}", flush=True)
    return answer


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, data):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"status": "ready", "backend": "local_codex_chatgpt_subscription",
                             "model": MODEL, "reasoning_effort": EFFORT})
        else:
            self.reply(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            return self.reply(404, {"error": "not found"})
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 64 * 1024 * 1024:
                return self.reply(413, {"error": "request too large or empty"})
            self.reply(200, complete(json.loads(self.rfile.read(size)), self.server.jobs, self.server.codex))
        except (InvalidRequest, json.JSONDecodeError) as exc:
            self.reply(400, {"error": {"type": type(exc).__name__, "message": str(exc)}})
        except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as exc:
            print(f"bridge failure: {type(exc).__name__}: {exc}", flush=True)
            self.reply(502, {"error": {"type": type(exc).__name__, "message": str(exc)}})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18881)
    parser.add_argument("--jobs", type=Path, default=PROJECT / "runs" / "pro-subscription-bridge")
    parser.add_argument("--codex", default=shutil.which("codex"))
    args = parser.parse_args()
    if not args.codex:
        parser.error("codex CLI is required")
    args.jobs.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.jobs, server.codex = args.jobs, args.codex
    print(f"Pro subscription planner bridge ready on 127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
