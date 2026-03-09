from agent_os.providers.base import ProviderBase
from agent_os.providers.deepseek_provider import DeepSeekChatProvider
from agent_os.providers.gemini_provider import GeminiFlashProvider


def get_provider(name: str = "gemini_flash") -> ProviderBase:
    if name == "deepseek_reasoner":
        return DeepSeekChatProvider(model_name="deepseek-reasoner")
    if name == "deepseek_chat":
        return DeepSeekChatProvider(model_name="deepseek-chat")
    if name == "gemini_flash":
        return GeminiFlashProvider()
    return GeminiFlashProvider()
