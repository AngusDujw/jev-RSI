import base64
import io
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from PIL import Image


def key(cfg):
    value = os.environ.get(cfg.get("key_env", ""))
    if not value:
        p = Path(cfg["key_file"]).expanduser()
        value = p.read_text().strip()
        if value.startswith("{"):
            value = json.loads(value)[cfg.get("key_field", "OPENAI_API_KEY")]
    if not value:
        raise ValueError("Empty API credential")
    return value


def image_url(rgb):
    stream = io.BytesIO()
    Image.fromarray(rgb).save(stream, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(stream.getvalue()).decode()


class API:
    def __init__(self, cfg, log, role):
        self.cfg, self.log, self.role = cfg, log, role
        self.auth_mode = cfg.get("auth_mode", "bearer")
        if self.auth_mode == "none":
            endpoint = urlsplit(cfg["base_url"])
            if endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError("Unauthenticated API routes must use a loopback HTTP endpoint")
            self.credential = None
        elif self.auth_mode == "bearer":
            self.credential = key(cfg)
        else:
            raise ValueError("Unknown API auth_mode")
        # Explicit proxy avoids malformed global ALL_PROXY/NO_PROXY settings.
        self.client = httpx.Client(timeout=cfg.get("timeout_s", 60), follow_redirects=False,
                                   trust_env=False, proxy=cfg.get("proxy"))
        self.calls = 0

    def post(self, endpoint, payload):
        start = time.monotonic()
        self.calls += 1
        record = {"kind": "api", "role": self.role, "call": self.calls, "requested_model": payload["model"]}
        try:
            headers = {"Authorization": "Bearer " + self.credential} if self.credential else {}
            r = self.client.post(self.cfg["base_url"].rstrip("/") + endpoint,
                                 json=payload, headers=headers)
            record["http_status"] = r.status_code
            if r.status_code != 200:
                try:
                    body = r.json()
                    detail = str(body.get("detail", body.get("error", "")))[:250] if isinstance(body,dict) else "non-JSON error body"
                except ValueError:
                    detail = "non-JSON error body"
                if self.credential:
                    detail = detail.replace(self.credential, "[redacted]")
                raise RuntimeError(f"{self.role} HTTP {r.status_code}: {detail}")
            if r.headers.get("content-type", "").startswith("text/event-stream"):
                d = None
                completed_items = {}
                for line in r.text.splitlines():
                    if line.startswith("data: ") and line[6:] != "[DONE]":
                        event = json.loads(line[6:])
                        if isinstance(event.get("response"),dict):
                            metadata=event["response"]
                            record.update(response_id=metadata.get("id"),model=metadata.get("model"))
                        if event.get("type") == "response.output_item.done":
                            completed_items[event["output_index"]] = event["item"]
                        if event.get("type") == "response.completed":
                            d = event["response"]
                        elif event.get("type") in {"error", "response.failed", "response.incomplete"}:
                            metadata=event.get("response",{})
                            detail=metadata.get("error") or event.get("error") or metadata.get("incomplete_details") or event.get("message")
                            safe=str(detail)
                            if self.credential:
                                safe=safe.replace(self.credential,"[redacted]")
                            safe=safe[:500]
                            record.update(stream_terminal=event.get("type"),stream_error=safe)
                            raise RuntimeError("Responses stream failed/incomplete: "+safe)
                if d is None:
                    raise RuntimeError("Responses stream ended without completion")
                if not d.get("output") and completed_items:
                    d["output"] = [completed_items[i] for i in sorted(completed_items)]
            else:
                d = r.json()
            record.update(model=d.get("model"), usage=d.get("usage"))
            if d.get("model_provenance"):
                record["model_provenance"] = d["model_provenance"]
            expected = self.cfg.get("expected_model_prefix", payload["model"])
            if not str(d.get("model", "")).startswith(expected):
                raise RuntimeError(f"{self.role} returned unexpected model {d.get('model')}")
            return d
        except Exception as e:
            record["error_type"] = type(e).__name__
            raise
        finally:
            record["seconds"] = round(time.monotonic() - start, 3)
            self.log(record)

    def chat(self, system, state, cameras=None, schema=None):
        content = [{"type": "text", "text": "Respond with JSON.\n" + json.dumps(state, ensure_ascii=False, allow_nan=False)}]
        for name, frame in (cameras or {}).items():
            content += [{"type": "text", "text": f"Camera {name}, {frame.rgb.shape[1]}x{frame.rgb.shape[0]}"},
                        {"type": "image_url", "image_url": {"url": image_url(frame.rgb), "detail": "high"}}]
        payload = {"model": self.cfg["model"], "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
                   "max_completion_tokens": self.cfg.get("max_tokens", 6000), "response_format": {"type": "json_object"}}
        if self.cfg.get("reasoning_effort"):
            payload["reasoning_effort"] = self.cfg["reasoning_effort"]
        if schema:
            payload["messages"][0]["content"] += "\nReturn JSON satisfying this schema:\n" + json.dumps(schema)
        if self.cfg.get("wire") == "responses":
            converted = []
            for item in content:
                if item["type"] == "text":
                    converted.append({"type": "input_text", "text": item["text"]})
                else:
                    converted.append({"type": "input_image", "image_url": item["image_url"]["url"], "detail": "high"})
            request = {"model": self.cfg["model"], "instructions": payload["messages"][0]["content"],
                       "input": [{"role": "user", "content": converted}], "stream": True, "store": False,
                       "max_output_tokens": self.cfg.get("max_tokens", 6000), "text": {"format": {"type": "json_object"}}}
            if self.cfg.get("reasoning_effort"):
                request["reasoning"] = {"effort": self.cfg["reasoning_effort"]}
            for field in self.cfg.get("omit_fields", []):
                request.pop(field, None)
            d = self.post("/responses", request)
            if d.get("status") != "completed":
                raise RuntimeError("Incomplete Responses result")
            text = "".join(p["text"] for item in d.get("output", []) if item.get("type") == "message" for p in item.get("content", []) if p.get("type") == "output_text")
            return json.loads(text)
        d = self.post("/chat/completions", payload)
        c = d["choices"][0]
        if c.get("finish_reason") != "stop":
            raise RuntimeError("Incomplete model output")
        return json.loads(c["message"]["content"])

    def jev(self, state, questions):
        d = self.post("/systemone", {"model": self.cfg["model"], "state": state, "questions": questions})
        answers = d["answers"]
        for name, q in questions.items():
            a = answers[name]
            probs = a["probabilities"]
            if a.get("type") != "choice" or a["choice"] not in q["criteria"] or set(probs) != set(q["criteria"]):
                raise ValueError("Invalid Jev choice shape")
            import math
            if any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1 for v in [a["confidence"], *probs.values()]):
                raise ValueError("Invalid probability")
            if abs(sum(probs.values()) - 1) > .02:
                raise ValueError("Invalid probability distribution")
        return answers

    def close(self):
        self.client.close()
