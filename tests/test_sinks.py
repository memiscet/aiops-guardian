import json
import socket
import urllib.request

import boto3
import pytest
from botocore.stub import Stubber

from aiops import sinks
from aiops.sinks import MiniStackSink, SinkError, make_session, validate_endpoint


@pytest.mark.parametrize("url", ["http://localhost:4570", "http://127.0.0.1:4570", "http://localhost:4570/"])
def test_local_endpoint_accepted(url):
    assert validate_endpoint(url).endswith(":4570")


@pytest.mark.parametrize("url", ["http://localhost:4566", "http://localhost:4567", "https://localhost:4570", "http://0.0.0.0:4570",
                                 "http://s3.amazonaws.com", "http://sqs.us-east-1.amazonaws.com:4570", "http://user@localhost:4570",
                                 "http://192.168.56.20:4570", "http://localhost:4570/x", ""])
def test_non_local_or_wrong_port_endpoints_refused(url):
    with pytest.raises(SinkError):
        validate_endpoint(url)


def test_session_ignores_shared_aws_profiles_and_env_endpoints(monkeypatch, tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text("[profile prod-primary]\nendpoint_url = https://example.invalid\nregion = eu-west-1\n")
    monkeypatch.setenv("AWS_PROFILE", "prod-primary")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(cfg))
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://localhost:4566")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "REALLOOKINGKEY")
    sink = MiniStackSink("http://localhost:4570")
    assert sink.s3.meta.endpoint_url == "http://localhost:4570" and sink.sqs.meta.endpoint_url == "http://localhost:4570"
    assert sink.s3.meta.region_name == "us-east-1"
    assert make_session().get_credentials().access_key == "test"


def test_publish_uploads_redacted_objects_and_sends_message():
    sink = MiniStackSink("http://localhost:4570")
    secret = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1"
    with Stubber(sink.s3) as s3, Stubber(sink.sqs) as sqs:
        for _ in range(3):
            s3.add_response("put_object", {})
        sqs.add_response("get_queue_url", {"QueueUrl": "http://localhost:4570/000000000000/aiops-guardian-incidents"})
        sqs.add_response("send_message", {"MessageId": "m-1", "MD5OfMessageBody": "x"})
        report = {"decision": "allowed", "result": "r", "diagnosis": {"category": "oom_killed"}, "note": f"token={secret}"}
        refs = sink.publish("run-1", report, f"evidence password=hunter2 {secret}", [{"step_id": "a"}])
    assert refs["message_id"] == "m-1" and len(refs["objects"]) == 3 and refs["endpoint"] == "http://localhost:4570"
    assert all(k.startswith("incidents/run-1/") for k in refs["objects"])


def test_publish_error_is_wrapped_and_redacted():
    sink = MiniStackSink("http://localhost:4570")
    with Stubber(sink.s3) as s3:
        s3.add_client_error("put_object", "InternalError", "boom Authorization: Bearer abcdefghijklmnop12345")
        with pytest.raises(SinkError) as exc:
            sink.publish("run-2", {}, "e", [])
    assert "abcdefghijklmnop" not in str(exc.value)


def _ministack_up():
    try:
        with socket.create_connection(("127.0.0.1", 4570), timeout=1):
            return json.load(urllib.request.urlopen("http://127.0.0.1:4570/_ministack/health", timeout=2))["version"] is not None
    except Exception:
        return False


@pytest.mark.skipif(not _ministack_up(), reason="Guardian MiniStack not running on 127.0.0.1:4570")
def test_integration_round_trip_against_local_ministack():
    sink = MiniStackSink("http://localhost:4570")
    run_id = "pytest-" + __import__("uuid").uuid4().hex[:8]
    refs = sink.publish(run_id, {"decision": "allowed", "result": "ok", "diagnosis": {"category": "app_exit_nonzero"}}, "evidence", [{"step_id": "x"}])
    key = f"incidents/{run_id}/report.json"
    body = sink.s3.get_object(Bucket=sinks.BUCKET, Key=key)["Body"].read().decode()
    assert json.loads(body)["decision"] == "allowed"
    url = sink.sqs.get_queue_url(QueueName=sinks.QUEUE)["QueueUrl"]
    seen = []
    for _ in range(10):
        for m in sink.sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10, WaitTimeSeconds=0).get("Messages", []):
            if json.loads(m["Body"]).get("run_id") == run_id:
                seen.append(json.loads(m["Body"]))
            sink.sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])
        if seen:
            break
    assert seen and seen[0]["report_key"] == key and seen[0]["report_sha256"] == refs["objects"][key]
    for k in refs["objects"]:
        sink.s3.delete_object(Bucket=sinks.BUCKET, Key=k)
