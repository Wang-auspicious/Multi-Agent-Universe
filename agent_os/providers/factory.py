from agent_os.providers.base import ProviderBase
from agent_os.providers.deepseek_provider import DeepSeekChatProvider
from agent_os.providers.gemini_provider import GeminiFlashProvider
from agent_os.providers.sub2api_provider import Sub2ApiResponsesProvider


def get_provider(name: str = "sub2api_default") -> ProviderBase:
    if name == "deepseek_reasoner":
        return DeepSeekChatProvider(model_name="deepseek-reasoner")
    if name == "deepseek_chat":
        return DeepSeekChatProvider(model_name="deepseek-chat")
    if name == "gemini_flash":
        return GeminiFlashProvider()
    if name in {"sub2api_default", "sub2api_responses", "codex_responses"}:
        return Sub2ApiResponsesProvider(model_name="gpt-5.4")
    if name == "sub2api_fast":
        return Sub2ApiResponsesProvider(model_name="gpt-5.4", reasoning_effort="medium", verbosity="medium")
    if name == "sub2api_strong":
        return Sub2ApiResponsesProvider(model_name="gpt-5.4", reasoning_effort="high", verbosity="high")
    if name == "sub2api_final":
        return Sub2ApiResponsesProvider(model_name="gpt-5.4", reasoning_effort="medium", verbosity="high")
    return Sub2ApiResponsesProvider(model_name="gpt-5.4")
