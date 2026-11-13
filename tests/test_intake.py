from khutlisa import intake, llm


def test_extract_json_from_fenced_answer():
    assert llm._extract_json('Here you go:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert llm._extract_json('{"a": [1, 2]} trailing words') == {"a": [1, 2]}


def test_history_from_words_fills_missing_lists(monkeypatch):
    monkeypatch.setattr(llm, "ask", lambda prompt, **kw: '{"language": "Spanish", "given_names": ["Luz"]}')
    h = intake.history_from_words("Soy Luz")
    assert h["given_names"] == ["Luz"] and h["family_names"] == [] and h["places"] == [] and h["employers"] == []


def test_prompt_carries_the_words_and_forbids_inventing(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm, "ask", lambda prompt, **kw: seen.setdefault("p", prompt) and "{}")
    intake.history_from_words("Nagtrabaho ako sa Daly City")
    assert "Nagtrabaho ako sa Daly City" in seen["p"] and "Do not invent" in seen["p"]


def test_the_follow_up_is_said_to_ask_for_the_postcode_when_a_place_has_none(monkeypatch):
    answer = {"language": "Spanish", "given_names": ["Luz"], "family_names": ["Sereno"],
              "places": [{"city": "Salinas", "region": "CA", "country": "US"}],
              "follow_up": "¿Recuerda el código postal de donde vivía en Salinas?", "follow_up_english": "Do you remember the postcode?"}
    monkeypatch.setattr(llm, "ask", lambda prompt, **kw: __import__("json").dumps(answer))
    got = intake.understand("Soy Luz Sereno, viví en Salinas")
    assert got["follow_up_asks_for"] == "postcode" and "código postal" in got["follow_up"]
    answer["places"][0]["postcode"] = "93905"
    assert intake.understand("Soy Luz Sereno")["follow_up_asks_for"] == "more"      # the postcode is there: it asks for something else
    answer["follow_up"] = ""
    assert intake.understand("Soy Luz Sereno")["follow_up_asks_for"] == ""
    prompt = " ".join(intake.PROMPT.split())
    assert "ask for that postcode and nothing else" in prompt and "the search never uses a street" in prompt
