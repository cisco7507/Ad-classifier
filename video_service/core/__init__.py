def run_pipeline_job(*args, **kwargs):
    from video_service.core.pipeline import run_pipeline_job as _run_pipeline_job
    return _run_pipeline_job(*args, **kwargs)


def process_single_video(*args, **kwargs):
    from video_service.core.pipeline import process_single_video as _process_single_video
    return _process_single_video(*args, **kwargs)


def run_agent_job(*args, **kwargs):
    from video_service.core.agent import run_agent_job as _run_agent_job
    return _run_agent_job(*args, **kwargs)


__all__ = ["run_pipeline_job", "process_single_video", "run_agent_job"]
