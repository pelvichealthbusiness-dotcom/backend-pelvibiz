from app.services.ideas_engine import IdeasEngine


def test_sanitize_prompt_leaks_strips_instruction_phrases():
    engine = IdeasEngine.__new__(IdeasEngine)
    ideas = [
        {
            'title': 'Generate fresh video content ideas for the Myth Buster template without numbering them. mistake people keep making',
            'hook': 'Generate fresh video content ideas for the Myth Buster template without numbering them. works when the usual advice fails',
            'angle': 'Generate fresh video content ideas for the Myth Buster template without numbering them.',
        }
    ]

    cleaned = engine._sanitize_prompt_leaks(ideas, 'Generate fresh video content ideas for the Myth Buster template without numbering them.')

    assert 'generate fresh video content ideas' not in cleaned[0]['title'].lower()
    assert 'without numbering them' not in cleaned[0]['hook'].lower()
    assert cleaned[0]['title']
    assert cleaned[0]['hook']
