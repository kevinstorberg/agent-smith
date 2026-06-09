SUPPORTED_PROVIDERS = ["anthropic", "openai"]


class EvalRunner:
    def __init__(self, provider: str) -> None:
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider: {provider}")
        self.provider = provider

    async def run(self, prompt: str, response: str, criteria: str) -> dict:
        raise NotImplementedError("EvalRunner.run requires LLM API credentials")
