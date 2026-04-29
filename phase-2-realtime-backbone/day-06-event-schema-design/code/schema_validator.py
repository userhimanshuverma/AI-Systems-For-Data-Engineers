"""
Schema Validator — Day 06: Event Schema Design
================================================
Validates events against the canonical schema before they are
published to Kafka. Invalid events are rejected at the producer,
not discovered downstream.

This is the enforcement layer for schema consistency.

In production: this logic runs inside the event SDK used by all
services. You can also use Confluent Schema Registry with Avro
for stronger enforcement with schema evolution support.

Run this to see validation in action on both valid and invalid events.
"""

import re
from datetime import datetime, timezone


# ── SCHEMA DEFINITION ─────────────────────────────────────────────────────────

# Required top-level fields and their expected types
REQUIRED_FIELDS: dict[str, type] = {
    "event_id":       str,
    "schema_version": str,
    "event_type":     str,
    "user_id":        str,
    "session_id":     str,
    "ts":             str,
}

# Optional but validated if present
OPTIONAL_FIELDS: dict[str, type] = {
    "context":          dict,
    "device":           dict,
    "user_properties":  dict,
    "data":             dict,
}

# event_type must match: domain.action (e.g., ui.button_click)
EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z_]+\.[a-z][a-z_]+$")

# ts must be ISO 8601 with UTC timezone
TS_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)

# user_id must match: u_ prefix + alphanumeric
USER_ID_PATTERN = re.compile(r"^u_[a-zA-Z0-9]+$")

# Known valid schema versions
VALID_SCHEMA_VERSIONS = {"1.0", "1.1", "1.2", "2.0"}


# ── VALIDATION RESULT ─────────────────────────────────────────────────────────

class ValidationResult:
    def __init__(self):
        self.errors:   list[str] = []
        self.warnings: list[str] = []

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def __str__(self) -> str:
        lines = []
        if self.valid:
            lines.append("  ✅ VALID")
        else:
            lines.append("  ❌ INVALID")
        for e in self.errors:
            lines.append(f"    ERROR:   {e}")
        for w in self.warnings:
            lines.append(f"    WARNING: {w}")
        return "\n".join(lines)


# ── VALIDATOR ─────────────────────────────────────────────────────────────────

def validate(event: dict) -> ValidationResult:
    """
    Validates an event dict against the canonical schema.
    Returns a ValidationResult with errors and warnings.

    Errors   → event must be rejected (sent to dead-letter topic)
    Warnings → event is accepted but flagged for review
    """
    result = ValidationResult()

    # 1. Check required fields exist and have correct types
    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in event:
            result.error(f"Missing required field: '{field}'")
        elif not isinstance(event[field], expected_type):
            result.error(
                f"Field '{field}' must be {expected_type.__name__}, "
                f"got {type(event[field]).__name__}"
            )

    # 2. Validate event_type format (domain.action)
    if "event_type" in event and isinstance(event["event_type"], str):
        if not EVENT_TYPE_PATTERN.match(event["event_type"]):
            result.error(
                f"event_type '{event['event_type']}' must match pattern "
                f"'domain.action' (e.g., 'ui.button_click')"
            )

    # 3. Validate timestamp format
    if "ts" in event and isinstance(event["ts"], str):
        if not TS_PATTERN.match(event["ts"]):
            result.error(
                f"ts '{event['ts']}' must be ISO 8601 with UTC timezone "
                f"(e.g., '2026-04-27T14:32:01.412Z')"
            )

    # 4. Validate user_id format
    if "user_id" in event and isinstance(event["user_id"], str):
        if not USER_ID_PATTERN.match(event["user_id"]):
            result.warn(
                f"user_id '{event['user_id']}' does not match expected "
                f"format 'u_<alphanumeric>' — check naming convention"
            )

    # 5. Validate schema_version is known
    if "schema_version" in event and isinstance(event["schema_version"], str):
        if event["schema_version"] not in VALID_SCHEMA_VERSIONS:
            result.warn(
                f"schema_version '{event['schema_version']}' is not in "
                f"known versions {VALID_SCHEMA_VERSIONS}"
            )

    # 6. Validate optional fields have correct types if present
    for field, expected_type in OPTIONAL_FIELDS.items():
        if field in event and not isinstance(event[field], expected_type):
            result.error(
                f"Field '{field}' must be {expected_type.__name__} if present, "
                f"got {type(event[field]).__name__}"
            )

    # 7. Warn if context block is missing (not required, but strongly recommended)
    if "context" not in event:
        result.warn("Missing 'context' block — event will produce a low-quality embedding")

    # 8. Warn if user_properties is missing
    if "user_properties" not in event:
        result.warn("Missing 'user_properties' — AI layer cannot filter by user state")

    return result


# ── KAFKA PUBLISH GATE ────────────────────────────────────────────────────────

def publish_with_validation(event: dict, topic: str = "user.events") -> bool:
    """
    Validates event before publishing to Kafka.
    Returns True if published, False if rejected to dead-letter topic.

    In production:
        if result.valid:
            producer.produce(topic=topic, key=event['user_id'], value=json.dumps(event))
        else:
            producer.produce(topic='user.events.dead-letter', ...)
    """
    result = validate(event)
    if result.valid:
        print(f"  [PUBLISH]  → {topic}  event_type={event.get('event_type','?')}")
        if result.warnings:
            for w in result.warnings:
                print(f"  [WARN]     {w}")
        return True
    else:
        print(f"  [REJECT]   → user.events.dead-letter  event_type={event.get('event_type','?')}")
        for e in result.errors:
            print(f"  [ERROR]    {e}")
        return False


# ── TEST EVENTS ───────────────────────────────────────────────────────────────

def make_valid_event() -> dict:
    return {
        "event_id":       "evt_a1b2c3d4",
        "schema_version": "1.0",
        "event_type":     "ui.button_click",
        "user_id":        "u_4821",
        "session_id":     "sess_9x8y7z",
        "ts":             datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "context": {
            "page":         "/pricing",
            "element_id":   "cta_upgrade_plan",
            "element_text": "Upgrade to Pro",
        },
        "device": {"type": "mobile", "os": "iOS 17"},
        "user_properties": {"plan": "free", "country": "US", "segment": "at_risk"},
    }

TEST_EVENTS = [
    ("Valid event",                    make_valid_event()),
    ("Missing event_id",               {k: v for k, v in make_valid_event().items() if k != "event_id"}),
    ("Wrong event_type format",        {**make_valid_event(), "event_type": "click"}),
    ("Unix timestamp (wrong format)",  {**make_valid_event(), "ts": "1714225921"}),
    ("Wrong type for context",         {**make_valid_event(), "context": "not a dict"}),
    ("Missing context (warning only)", {k: v for k, v in make_valid_event().items() if k != "context"}),
    ("Unknown schema version",         {**make_valid_event(), "schema_version": "99.0"}),
    ("Weak schema (bad naming)",       {"uid": "u_4821", "evt": "click", "t": 1714225921}),
]


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("SCHEMA VALIDATOR — Event validation before Kafka publish")
    print("=" * 65)

    passed = 0
    rejected = 0

    for label, event in TEST_EVENTS:
        print(f"\n[TEST] {label}")
        result = validate(event)
        print(result)
        ok = publish_with_validation(event)
        if ok:
            passed += 1
        else:
            rejected += 1

    print(f"\n{'='*65}")
    print(f"  Results: {passed} published | {rejected} rejected to dead-letter")
    print(f"  Invalid events never reach Kafka — schema is enforced at source.")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
