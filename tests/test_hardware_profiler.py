from video_service.core.hardware_profiler import get_system_profile


def test_system_profile_shape():
    payload = get_system_profile()
    assert "timestamp" in payload
    assert "hardware" in payload
    assert "capability_matrix" in payload
    assert "warnings" in payload

    hw = payload["hardware"]
    assert "cpu_count_logical" in hw
    assert "total_ram_mb" in hw
    assert "accelerator" in hw

