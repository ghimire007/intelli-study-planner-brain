"""Verify the real authenticated demo using a credential file, never printed secrets.

Run: python -m scripts.verify_demo --credentials /path/to/private-login.json
The file contains {"email": "...", "password": "..."}. Connect a key in Settings first.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx
from app.llm.registry import Provider, provider_for
from app.services.study_plan import parse_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:7777")
    parser.add_argument("--model", default="gemini-3.5-flash-lite")
    parser.add_argument("--record", type=Path, default=Path("tests/fixtures/sols_transfer_flat.txt"))
    parser.add_argument("--revision", default="Revise my plan: preserve all historical/current enrolments and show every remaining session chronologically.")
    parser.add_argument("--out", type=Path, default=Path("/private/tmp/courseo-demo-verification"))
    args = parser.parse_args()
    credentials = json.loads(args.credentials.read_text())
    login = {key: credentials[key] for key in ("email", "password")}
    args.out.mkdir(parents=True, exist_ok=True, mode=0o700)

    with httpx.Client(base_url=args.base_url, timeout=210) as client:
        def call(method, path, body=None):
            response = client.request(method, path, json=body)
            print(f"{method} {path}: {response.status_code}", flush=True)
            if not response.is_success:
                try:
                    detail = response.json().get("detail")
                except ValueError:
                    detail = "Non-JSON server error; inspect the backend logs."
                raise RuntimeError(f"Demo request failed: {detail}")
            return response.json() if response.content else None

        def save(name, data):
            target = args.out / f"{name}.json"
            target.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            target.chmod(0o600)

        def check_plan(reply):
            content = reply["content"]
            plan = parse_plan(content)
            assert "| Year | Session | Subject Code | Subject Name | CP | Notes |" in content
            assert reply["requested_model"] == args.model
            rows = sum(len(t.subjects) for y in plan.plan for t in y.sessions)
            print(f"Plan validated: {rows} rows; selected={args.model}; provider-reported={reply['model']}", flush=True)
            return plan

        user = call("POST", "/api/v1/auth/login", login)
        assert all(user.get(key) for key in ("degree_code", "commencement_year", "campus", "major")), "Save the demo academic profile first."
        providers = call("GET", "/api/v1/keys/providers")["providers"]
        assert {p["provider"] for p in providers} == {p.value for p in Provider}
        provider = provider_for(args.model).value
        selected = next(p for p in providers if p["provider"] == provider)
        assert selected["has_usable_key"], f"Connect an active {provider} key in Settings first."
        keys = call("GET", "/api/v1/keys")
        credential = next(k for k in keys if k["provider"] == provider and k["status"] == "active")
        assert call("POST", f"/api/v1/keys/{credential['id']}/verify")["verified"]
        record = args.record.read_text()
        result = call("POST", "/api/v1/chat", {
            "message": "Create a complete study plan using my saved profile and enrolment record.",
            "input_type": "question", "model": args.model, "context": {"enrolment_record": record},
        })
        session = result["session_id"]
        for _ in range(3):
            if "```json" in result["reply"]["content"]:
                break
            result = call("POST", f"/api/v1/chat/{session}", {
                "message": f"Yes, I confirm course {user['degree_code']}, commencement year {user['commencement_year']}, campus {user['campus']}, major {user['major']}. Generate my complete study plan.",
                "model": args.model,
            })
        check_plan(result["reply"])
        save("plan", result)
        revision = call("POST", f"/api/v1/chat/{session}", {
            "message": args.revision, "model": args.model, "context": {"enrolment_record": record},
        })
        check_plan(revision["reply"])
        save("revision", revision)
        call("POST", "/api/v1/auth/logout")
        call("POST", "/api/v1/auth/login", login)
        history = call("GET", f"/api/v1/chat/{session}")
        assert history["messages"][-1]["content"] == revision["reply"]["content"]
        assert history["model"] == args.model
        save("restored", history)
        unauthenticated = httpx.get(f"{args.base_url}/api/v1/chat/{session}", timeout=30)
        assert unauthenticated.status_code == 401
        print(f"Demo passed: verified key, plan, revision, restored history, unauthenticated access denied. Evidence: {args.out}")


if __name__ == "__main__":
    main()
