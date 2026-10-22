"""Local-only MiniStack output: incident report to S3, incident event to SQS.

The endpoint is validated to be http://localhost:4570 or http://127.0.0.1:4570 (never another port, never a real AWS endpoint).
Credentials are hard-coded dummies; shared AWS config, credentials and profiles are ignored. MiniStack is an emulator and does not
prove real AWS IAM or S3/SQS behavior.
"""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import boto3
import botocore.session
from botocore.config import Config

from .mcp_adapter import redact

ALLOWED_HOSTS = {"localhost", "127.0.0.1"}
ALLOWED_PORT = 4570
BUCKET = "aiops-guardian-evidence"
QUEUE = "aiops-guardian-incidents"
DUMMY = {"aws_access_key_id": "test", "aws_secret_access_key": "test"}


class SinkError(RuntimeError):
    pass


def validate_endpoint(url: str) -> str:
    u = urlparse(url)
    if u.scheme != "http" or u.hostname not in ALLOWED_HOSTS or u.port != ALLOWED_PORT or u.path not in ("", "/") or u.username:
        raise SinkError(f"endpoint must be http://localhost:{ALLOWED_PORT} or http://127.0.0.1:{ALLOWED_PORT}")
    return f"http://{u.hostname}:{u.port}"


_ISOLATED = tempfile.TemporaryDirectory(prefix="guardian-aws-")


def make_session() -> boto3.Session:
    """Session that ignores ~/.aws config/credentials, AWS_PROFILE and AWS_* endpoint env vars: dummy credentials, fixed region."""
    base = Path(_ISOLATED.name)
    (base / "config").write_text("[default]\nregion = us-east-1\n")
    (base / "credentials").write_text("[default]\naws_access_key_id = test\naws_secret_access_key = test\n")
    core = botocore.session.Session(session_vars={
        "profile": (None, None, "default", None),
        "config_file": (None, None, str(base / "config"), None),
        "credentials_file": (None, None, str(base / "credentials"), None)})
    return boto3.Session(botocore_session=core, region_name="us-east-1", **DUMMY)


class MiniStackSink:
    def __init__(self, endpoint: str, session: boto3.Session | None = None, bucket: str = BUCKET, queue: str = QUEUE):
        self.endpoint = validate_endpoint(endpoint)
        session = session or make_session()
        cfg = Config(retries={"max_attempts": 1}, connect_timeout=3, read_timeout=5)
        self.s3 = session.client("s3", endpoint_url=self.endpoint, config=cfg)
        self.sqs = session.client("sqs", endpoint_url=self.endpoint, config=cfg)
        self.bucket, self.queue = bucket, queue

    def publish(self, run_id: str, report: dict, evidence_text: str, events: list[dict]) -> dict:
        """Uploads redacted report, evidence and audit events, then sends one SQS message. Returns references (no secrets)."""
        prefix = f"incidents/{run_id}"
        body = redact(json.dumps(report, sort_keys=True, indent=1, default=str))[0]
        objects = {
            f"{prefix}/report.json": body,
            f"{prefix}/evidence.txt": redact(evidence_text)[0],
            f"{prefix}/audit-events.jsonl": redact("\n".join(json.dumps(e, sort_keys=True) for e in events) + "\n")[0],
        }
        refs = {}
        try:
            for key, text in objects.items():
                self.s3.put_object(Bucket=self.bucket, Key=key, Body=text.encode(), ContentType="text/plain")
                refs[key] = hashlib.sha256(text.encode()).hexdigest()
            url = self.sqs.get_queue_url(QueueName=self.queue)["QueueUrl"]
            message = {"run_id": run_id, "decision": report.get("decision"), "result": report.get("result"),
                       "category": (report.get("diagnosis") or {}).get("category"), "bucket": self.bucket,
                       "report_key": f"{prefix}/report.json", "report_sha256": refs[f"{prefix}/report.json"]}
            sent = self.sqs.send_message(QueueUrl=url, MessageBody=json.dumps(message, sort_keys=True))
        except Exception as exc:
            raise SinkError(f"{type(exc).__name__}: {redact(str(exc))[0][:200]}") from exc
        return {"objects": refs, "message_id": sent["MessageId"], "queue": self.queue, "endpoint": self.endpoint}


def sink_from_env() -> MiniStackSink | None:
    url = os.environ.get("MINISTACK_ENDPOINT")
    return MiniStackSink(url) if url else None
