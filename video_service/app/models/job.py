from typing import List, Optional, Any
from pydantic import BaseModel, Field
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
    enable_vision: bool = True
    context_size: int = 8192
    workers: int = 2

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

class JobResponse(BaseModel):
    job_id: str
    status: str

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
