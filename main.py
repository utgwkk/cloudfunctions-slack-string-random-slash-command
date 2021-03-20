import os
import hmac
import hashlib
import time
import re
from flask import jsonify
from xeger import Xeger
import sys

# 40000 / 5 = 8000
# ref: https://api.slack.com/changelog/2018-04-truncating-really-long-messages
MAX_LENGTH = 8000

def calculate_max_length(reg):
    parsed = re.sre_parse.parse(reg)
    return MaxLengthCalculator(reg).calculate()

class MaxLengthCalculator:
    def __init__(self, reg, max_repeat=10):
        self._cache = {}
        self._max_repeat = max_repeat
        self._parsed = re.sre_parse.parse(reg)

    def calculate(self):
        self._cache.clear()
        return self._calculate(self._parsed)

    def _calculate(self, parsed):
        ret = 0
        for opcode, value in parsed:
            #print(opcode, value)
            opstr = str(opcode)
            if opstr == 'LITERAL':
                ret += self._calculate_literal(value)
            elif opstr == 'NOT_LITERAL':
                ret += self._calculate_not_literal(value)
            elif opstr == 'AT':
                ret += self._calculate_at(value)
            elif opstr == 'IN':
                ret += self._calculate_in(value)
            elif opstr == 'ANY':
                ret += self._calculate_any(value)
            elif opstr == 'BRANCH':
                ret += self._calculate_branch(value)
            elif opstr == 'SUBPATTERN':
                ret += self._calculate_group(value)
            elif opstr == 'MAX_REPEAT':
                ret += self._calculate_repeat(value)
            elif opstr == 'MIN_REPEAT':
                ret += self._calculate_repeat(value)
            elif opstr == 'GROUPREF':
                ret += self._calculate_groupref(value)
            else:
                print(f'unimplemented: {opcode}')
        return ret

    def _calculate_literal(self, value):
        return 1

    def _calculate_not_literal(self, value):
        return 1

    def _calculate_repeat(self, value):
        min_repeat, max_repeat, parsed = value
        if str(max_repeat) == 'MAXREPEAT':
            max_repeat = self._max_repeat
        return self._calculate(parsed) * max_repeat

    def _calculate_in(self, value):
        return 1

    def _calculate_at(self, value):
        return 0

    def _calculate_any(self, value):
        return 1

    def _calculate_branch(self, value):
        return max(self._calculate(v) for v in value[1])

    def _calculate_group(self, value):
        pattern_idx = 1 if sys.version_info < (3,6) else 3
        ret = self._calculate(value[pattern_idx])
        if value[0]:
            self._cache[value[0]] = ret
        return ret

    def _calculate_groupref(self, group):
        return self._cache[group]

# from: https://hacknote.jp/archives/39319/
def __generate_hmac_signature(timestamp, body):
    # Slack App - Basic Information - App Credentials に記載されている
    # Signing Secret
    secretkey = os.environ['SLACK_API_SIGNING_SECRET']
    secretkey_bytes = bytes(secretkey, 'UTF-8')

    message = "v0:{}:{}".format(timestamp, body)
    message_bytes = bytes(message, 'UTF-8')
    return hmac.new(secretkey_bytes, message_bytes, hashlib.sha256).hexdigest()


# from: https://hacknote.jp/archives/39319/
def is_valid_request(req):
    if "X-Slack-Request-Timestamp" not in req.headers \
            or "X-Slack-Signature" not in req.headers:
        return False

    request_timestamp = int(req.headers["X-Slack-Request-Timestamp"])
    now_timestamp = int(time.time())

    if abs(request_timestamp - now_timestamp) > (60 * 5):
        return False

    expected_hash = __generate_hmac_signature(
        req.headers["X-Slack-Request-Timestamp"],
        req.get_data(as_text=True)
    )

    expected = "v0={}".format(expected_hash)
    actual = req.headers["X-Slack-Signature"]

    return hmac.compare_digest(expected, actual)


def normalize(input_str: str) -> str:
    return re.sub(r'<([^|]+?)\|(^>)*?>', r'\1', input_str)

xeger = Xeger(limit=10)

def string_random(request):
    global xeger

    if not is_valid_request(request):
        return jsonify({'message': 'invalid request'}), 400

    input_regex = normalize(request.form['text'])

    if not input_regex:
        return jsonify({
            'text': 'Usage: `/string_random [regular expression]`',
            'response_type': 'ephemeral',
        })

    input_max_length = calculate_max_length(input_regex)
    if input_max_length > MAX_LENGTH:
        return jsonify({
            'text': f'The given regular expression `{input_regex}` yields too long string (its length is {input_max_length}). Maximum allowed length is {MAX_LENGTH}.',
            'response_type': 'in_channel',
        })

    try:
        response_text = '\n'.join(xeger.xeger(input_regex) for i in range(5))
    except Exception as e:
        response_text = f'Error: `{e}`'

    return jsonify({
        'text': response_text,
        'response_type': 'in_channel',
    })
