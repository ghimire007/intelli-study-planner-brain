from pydantic import BaseModel


class SOLSMeta(BaseModel):
    """Minimal metadata extracted from a SOLS paste — just enough to query the handbook."""
    degree_code: str  # e.g. "766"
    year: int         # commencement year — used for handbook DB lookup
    campus: str       # canonical campus name e.g. "Wollongong", "Liverpool", "Singapore"
