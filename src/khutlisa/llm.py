"""One door to a language model.

During development this hands the job to the Claude Code program already installed and signed in on the machine.
If ANTHROPIC_API_KEY is set, the same call goes to the API instead, which is how a deployed copy would run.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess


class ModelUnavailable(RuntimeError):
    for_screen = False        # True on a subclass whose message is a sentence a visitor may read


NOT_RECORDED = ("This public demonstration has no live language model. Its answers were recorded in advance for "
                "the demonstration people's words and documents only, and this is not one of them.")


class NotRecorded(ModelUnavailable):
    """A call in the public demonstration whose input has no recorded answer, on a copy with no live model."""
    for_screen = True


# A deployed copy can cap how many calls are made in a day (public_demo.DailyBudget.take is put here). It is
# called before every call and raises ModelUnavailable when the cap is reached. None means no cap.
gate = None

# The public demonstration has no key. The answers the model gave to its fixed inputs (the demonstration sound
# files, the sample documents, the invented holder file, the demonstration people's typed answers) were recorded
# once and ship with the app (recorded.py). When `recorded` is set, a call whose input is one of those returns the
# recorded answer and does not count against `gate`; any other call goes on as below. None means always live.
recorded = None


def input_key(prompt: str, files: list[str] | None = None) -> str:
    """The key of one call: a hash of the exact prompt and the bytes of every file, in order. The file's path
    is not part of it, so the same document stored in another claim folder has the same key."""
    h = hashlib.sha256(b"khutlisa-model-input-1\0" + prompt.encode("utf-8"))
    for f in files or []:
        with open(f, "rb") as fh:
            data = fh.read()
        h.update(b"\0file\0" + str(len(data)).encode() + b"\0" + data)
    return h.hexdigest()


def _extract_json(text: str):
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise ValueError("the model returned no JSON")
    return json.JSONDecoder().raw_decode(text[start:])[0]


def ask(prompt: str, *, files: list[str] | None = None, model: str = "sonnet", timeout: int = 180) -> str:
    """Plain text answer. `files` are local images or PDFs the model should look at."""
    if recorded is not None:
        answer = recorded.answer(input_key(prompt, files))
        if answer is not None:
            return answer
        if not os.environ.get("ANTHROPIC_API_KEY") and not shutil.which("claude"):
            raise NotRecorded(NOT_RECORDED)
    if gate is not None:
        gate()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _ask_api(prompt, files or [], model, timeout)
    exe = shutil.which("claude")
    if not exe:
        raise ModelUnavailable("no ANTHROPIC_API_KEY is set and the claude program is not installed")
    cmd = [exe, "-p", "--model", model, "--output-format", "json"]
    text = prompt
    if files:
        cmd += ["--allowedTools", "Read"]
        text += "\n\nRead these files before answering:\n" + "\n".join(os.path.abspath(f) for f in files)
    done = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=timeout, cwd="/tmp")
    if done.returncode != 0:
        raise ModelUnavailable(f"claude exited with {done.returncode}: {done.stderr[:300]}")
    out = json.loads(done.stdout)
    if out.get("is_error"):
        raise ModelUnavailable(str(out.get("result"))[:300])
    return out.get("result", "")


def ask_json(prompt: str, **kw):
    """Answer parsed as JSON. One retry if the first answer does not parse."""
    for attempt in range(2):
        text = ask(prompt + "\n\nAnswer with JSON only, no other text.", **kw)
        try:
            return _extract_json(text)
        except (ValueError, json.JSONDecodeError):
            if attempt:
                raise
    raise ValueError("unreachable")


_API_MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}


def _ask_api(prompt: str, files: list[str], model: str, timeout: int) -> str:
    import base64
    import mimetypes

    import httpx

    content: list[dict] = []
    for f in files:
        mime = mimetypes.guess_type(f)[0] or "application/octet-stream"
        data = base64.standard_b64encode(open(f, "rb").read()).decode()
        kind = "document" if mime == "application/pdf" else "image"
        content.append({"type": kind, "source": {"type": "base64", "media_type": mime, "data": data}})
    content.append({"type": "text", "text": prompt})
    r = httpx.post("https://api.anthropic.com/v1/messages", timeout=timeout,
                   headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
                   json={"model": _API_MODELS.get(model, model), "max_tokens": 4000,
                         "messages": [{"role": "user", "content": content}]})
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"])
