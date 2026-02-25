from typing import List, Optional, Any
from pydantic import BaseModel, Field, model_validator
from enum import Enum

class JobMode(str, Enum):
    pipeline = "pipeline"
    agent = "agent"

class JobSettings(BaseModel):
    categories: str = ""
    provider: str = "Gemini CLI"
    model_name: str = "Gemini CLI Default"
    ocr_engine: str = "EasyOCR"
    ocr_mode: str = "🚀 Fast"
    scan_mode: str = "Tail Only"
    override: bool = False
    enable_search: bool = True
    enable_web_search: Optional[bool] = None
    enable_agentic_search: Optional[bool] = None
    enable_vision: bool = True
    context_size: int = 8192

    @model_validator(mode="before")
    @classmethod
    def _normalize_search_aliases(cls, data):
        if not isinstance(data, dict):
            return data

        enable_search = data.get("enable_search")
        enable_web_search = data.get("enable_web_search")
        enable_agentic_search = data.get("enable_agentic_search")

        if enable_search is None:
            if enable_web_search is not None:
                data["enable_search"] = bool(enable_web_search)
            elif enable_agentic_search is not None:
                data["enable_search"] = bool(enable_agentic_search)
        if enable_web_search is None:
            data["enable_web_search"] = bool(data.get("enable_search", True))
        if enable_agentic_search is None:
            data["enable_agentic_search"] = bool(data.get("enable_search", True))
        return data

class JobSettingsForm(JobSettings):
    mode: JobMode = JobMode.pipeline

class UrlBatchRequest(BaseModel):
    mode: JobMode = JobMode.pipeline
    urls: List[str]
    settings: JobSettings

class FolderRequest(BaseModel):
    mode: JobMode = JobMode.pipeline
    folder_path: str
    settings: JobSettings

class FilePathRequest(BaseModel):
    mode: JobMode = JobMode.pipeline
    file_path: str
    settings: JobSettings

class JobResponse(BaseModel):
    job_id: str
    status: str

class BulkDeleteRequest(BaseModel):
    job_ids: List[str]

class JobStatus(BaseModel):
    job_id: str
    status: str
    stage: Optional[str] = None
    stage_detail: Optional[str] = None
    created_at: str
    updated_at: str
    progress: float
    error: Optional[str]
    settings: Optional[JobSettings]
    mode: Optional[JobMode]
    url: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    category_id: Optional[str] = None
