from agent_os.providers.sub2api_provider import Sub2ApiResponsesProvider


def test_sub2api_provider_extracts_output_text() -> None:
    provider = Sub2ApiResponsesProvider(api_key="test-key")
    payload = {
        "model": "gpt-5.4",
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "hello"},
                    {"type": "output_text", "text": "world"},
                ],
            }
        ],
        "usage": {"input_tokens": 12, "output_tokens": 7},
    }

    assert provider._extract_output_text(payload) == "hello\nworld"
    assert provider._usage_tokens(payload) == (12, 7)


def test_sub2api_provider_falls_back_to_direct_output_text() -> None:
    provider = Sub2ApiResponsesProvider(api_key="test-key")
    payload = {"output_text": "direct text"}

    assert provider._extract_output_text(payload) == "direct text"
