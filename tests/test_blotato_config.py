from app.config import Settings


def test_blotato_settings_have_correct_defaults():
    fields = Settings.model_fields
    assert "blotato_poll_interval" in fields
    assert "blotato_poll_timeout" in fields
    assert "blotato_max_retries" in fields
    assert fields["blotato_poll_interval"].default == 2
    assert fields["blotato_poll_timeout"].default == 60
    assert fields["blotato_max_retries"].default == 3
