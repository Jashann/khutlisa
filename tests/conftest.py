"""No test may reach a language model, the speech engine or the network. Each test that needs an answer from the
model replaces `khutlisa.llm.ask` itself; anything that slips through fails here instead of calling out. The
Airwallex keys on the machine are hidden too, so a test can only ever talk to the fake Airwallex it was given."""
import httpx
import pytest

from khutlisa import airwallex, llm, speech


@pytest.fixture(autouse=True)
def no_model(monkeypatch, tmp_path):
    def refuse(*args, **kwargs):
        raise llm.ModelUnavailable("the tests do not call a model")

    def silent(path):
        raise speech.SpeechUnavailable("the tests do not run the speech engine")

    monkeypatch.setattr(llm, "ask", refuse)
    monkeypatch.setattr(llm, "recorded", None)      # a public demonstration app made by a test sets it
    monkeypatch.setattr(speech, "transcribe", silent)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def no_network(self, request):
        raise AssertionError(f"a test tried to reach the network: {request.method} {request.url.host}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_network)
    monkeypatch.setattr(airwallex, "CREDENTIALS_FILE", tmp_path / "no-airwallex-keys")
    monkeypatch.delenv("AWX_CLIENT_ID", raising=False)
    monkeypatch.delenv("AWX_API_KEY", raising=False)
    monkeypatch.delenv("KHUTLISA_PAYER_KEY", raising=False)
    # No test may reach the real Metal testnet: the keys on this machine are hidden, so funding on Metal is off
    # unless a test hands the app a FakeMetal.
    monkeypatch.setenv("KHUTLISA_METAL_HOME", str(tmp_path / "no-metal-keys"))
    monkeypatch.delenv("METAL_RPC_URL", raising=False)
    monkeypatch.delenv("KHUTLISA_METAL_SCALE", raising=False)
