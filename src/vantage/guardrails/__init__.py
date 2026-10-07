"""Three guardrail stages: input (scope/injection), SQL (SELECT-only, allowlist,
LIMIT), and output (numeric grounding)."""

from .errors import GuardrailError, InputRejected, UnsafeSQLError
from .input import check_input
from .output import check_grounding
from .sql import validate_sql

__all__ = [
    "check_input",
    "validate_sql",
    "check_grounding",
    "GuardrailError",
    "InputRejected",
    "UnsafeSQLError",
]
