"""webhook 的 body 編碼與 HMAC 簽章：golden 值以 Python 的 hmac 另外算出。"""

from app.webhooks.signing import encode, headers, sign

SECRET = 's' * 32
TS = 1793865600
BODY = b'{"event":"job.finished","jobId":"job_x"}'
GOLDEN = 'v1=da6062c9083af0871bd5b0210dbf666128432245739944acb0a12a0fdeb11501'


def test_encode_is_compact_utf8_and_keeps_key_order() -> None:
    assert encode({'event': 'job.finished', 'jobId': 'job_x'}) == BODY
    assert encode({'brief': '週年慶'}) == '{"brief":"週年慶"}'.encode()


def test_sign_matches_the_golden_value() -> None:
    assert sign(SECRET, TS, BODY) == GOLDEN
    assert sign(SECRET, TS + 1, BODY) != GOLDEN
    assert sign('x' * 32, TS, BODY) != GOLDEN


def test_headers() -> None:
    assert headers(webhook_id='wh_1', event='job.finished', secret=SECRET, timestamp=TS, body=BODY) == {
        'Content-Type': 'application/json; charset=utf-8',
        'User-Agent': 'genai-agent-webhook/1',
        'X-Webhook-Id': 'wh_1',
        'X-Webhook-Event': 'job.finished',
        'X-Webhook-Timestamp': str(TS),
        'X-Webhook-Signature': GOLDEN,
    }
