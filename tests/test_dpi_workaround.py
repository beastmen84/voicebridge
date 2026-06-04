from voicebridge_qt import should_force_100_percent_dpi


def test_should_force_100_percent_dpi_only_for_1080p_high_dpi() -> None:
    assert should_force_100_percent_dpi((1920, 1080), 125)
    assert should_force_100_percent_dpi((1920, 1080), 150)

    assert not should_force_100_percent_dpi((1920, 1080), 100)
    assert not should_force_100_percent_dpi((2560, 1600), 150)
    assert not should_force_100_percent_dpi((1280, 720), 150)
    assert not should_force_100_percent_dpi(None, 150)
    assert not should_force_100_percent_dpi((1920, 1080), None)
