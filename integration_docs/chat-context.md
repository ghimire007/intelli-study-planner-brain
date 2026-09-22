# Chat context handoff

Both chat POST routes accept optional `context.profile` (degree_code, major,
campus, commencement_year, elective_interests) and `context.enrolment_record`.
Unknown keys in context are rejected. Codes are 3-4 digit strings; years are
integers from 1900 to 2100. Records and messages are limited to 100,000 characters.
Clients that omit context keep working, including explicit enrolment input.

The authenticated database User supplies the authoritative saved profile.
Client profile values are hints: they can fill unknown values, but cannot select
an account, authorize a session, or overwrite a differing saved value. Nulls and
omissions retain known data; empty elective interests select degree-based advice.

Session ownership is checked before reading checkpoints. This backend has no
separate account enrolment-record store: an existing session's projected record
is loaded from its checkpoint; a saved browser record must be supplied as context.
Records are structurally parsed, allowlist-projected, and scrubbed before graph
invocation. Context never gets concatenated into the user's message. Ordinary
message text retains its whitespace and wording except existing PII redaction;
messages containing records still undergo projection.

State tracks per-field sources and confirmation, unresolved conflicts, and
previously observed source values. Repeated stale hints cannot undo conversation
corrections or reopen a resolved conflict. New conflicting observations leave
current values intact and prompt a targeted clarification. Explicit confirmations
are persisted by the model's confirm_metadata_tool, which accepts partial updates.
Saved fields are candidates, not automatically student-confirmed. The earliest
record year is only a commencement candidate (especially for transfer students).

Degree titles come from the packaged catalog in app/services/course_catalog.py,
whose values are checked against seeds/scraped/course_*.json by tests. For example,
766 identifies Bachelor of Computer Science. Unknown courses have no invented
title or default code. Existing database profile values are used as stored.

All conversational replies still come from the selected model. Intake instructions
are context-sensitive; greetings/general questions do not require a record.
Handbook/tool success is required before claims of verification. UTF-8/Markdown
and the existing fenced JSON plan format are preserved without HTML escaping.

Invalid context/records return 422 without changing checkpoint state. Missing or
inaccessible sessions return 404; unavailable handbooks return 503. No API response
shape or database migration is changed. Deploy these backend files together; older
backends can silently ignore context because it was not declared in ChatRequest.
