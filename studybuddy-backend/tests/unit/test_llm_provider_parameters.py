import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.core import ai_service


@pytest.mark.parametrize('streaming', [False, True])
@pytest.mark.parametrize('provider', ['mimo', 'openai'])
def test_provider_request_parameters(monkeypatch, provider, streaming):
    llm = settings.config.llm.model_copy(update={'provider': provider, 'reasoning_effort': 'none'})
    monkeypatch.setattr(settings, 'config', settings.config.model_copy(update={'llm': llm}))
    create = AsyncMock(return_value=object())
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(ai_service, '_get_client', lambda: client)
    ai_service._breaker.on_success()
    call = ai_service.call_llm_stream if streaming else ai_service.call_llm
    asyncio.run(call([{'role': 'user', 'content': 'synthetic request'}], max_tokens=123))
    kwargs = create.call_args.kwargs
    if provider == 'mimo':
        assert kwargs['max_tokens'] == 123
        assert kwargs['extra_body'] == {'thinking': {'type': 'disabled'}}
        assert 'max_completion_tokens' not in kwargs
        assert 'reasoning_effort' not in kwargs
    else:
        assert kwargs['max_completion_tokens'] == 123
        assert kwargs['reasoning_effort'] == 'none'
        assert 'max_tokens' not in kwargs
        assert 'extra_body' not in kwargs
