from typing import List, Optional, Any
from pydantic import BaseModel, Field

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
    mode: str = "pipeline"

class UrlBatchRequest(BaseModel):
    mode: str = "pipeline"
    urls: List[str]
    settings: JobSettings

class FolderRequest(BaseModel):
    mode: str = "pipeline"
    folder_path: str
    settings: JobSettings

class JobResponse(BaseModel):
    job_id: str
    status: str

class JobStatus(BaseModel):
    job_id: str
    status: str
    created_at: str
    updated_at: str
    progress: float
    error: Optional[str]
    settings: Optional[JobSettings]
    mode: Optional[str]
