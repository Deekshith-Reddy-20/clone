import enum


class MembershipRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    operator = "operator"
    viewer = "viewer"


class EmployeeStatus(str, enum.Enum):
    draft = "draft"
    published = "published"
    archived = "archived"


class CallMode(str, enum.Enum):
    instant = "instant"
    bulk = "bulk"
    inbound = "inbound"


class KnowledgeStatus(str, enum.Enum):
    queued = "queued"
    ready = "ready"
    failed = "failed"
    archived = "archived"


class LeadStatus(str, enum.Enum):
    eligible = "eligible"
    suppressed = "suppressed"
    invalid = "invalid"


class PhoneNumberStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    suspended = "suspended"
    failed = "failed"


class CallDirection(str, enum.Enum):
    inbound = "inbound"
    outbound = "outbound"


class CallOutcome(str, enum.Enum):
    queued = "queued"
    dialing = "dialing"
    ringing = "ringing"
    connected = "connected"
    completed = "completed"
    no_answer = "no_answer"
    busy = "busy"
    failed = "failed"
    canceled = "canceled"


class CampaignStatus(str, enum.Enum):
    draft = "draft"
    scheduled = "scheduled"
    running = "running"
    paused = "paused"
    completed = "completed"
    canceled = "canceled"


class LedgerEntryType(str, enum.Enum):
    credit = "credit"
    debit = "debit"
    reserve = "reserve"
    release = "release"


class WebhookDeliveryStatus(str, enum.Enum):
    pending = "pending"
    delivered = "delivered"
    failed = "failed"
    dead_letter = "dead_letter"